from typing import Any, cast

from django.db.models import Q

from rest_framework import exceptions, serializers, status, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.models import Team, User
from posthog.models.resource_transfer.inter_project_transferer import (
    ResourceTransferVertex,
    build_resource_duplication_graph,
    dag_sort_duplication_graph,
    duplicate_resource_to_new_team,
    get_suggested_substitutions,
)
from posthog.models.resource_transfer.types import ResourceTransferKey
from posthog.models.resource_transfer.visitors import ResourceTransferVisitor
from posthog.rbac.user_access_control import UserAccessControl, model_to_resource


class ResourceTransferRequestSerializer(serializers.Serializer):
    source_team_id = serializers.IntegerField()
    destination_team_id = serializers.IntegerField()
    resource_kind = serializers.CharField()
    resource_id = serializers.CharField()


class SubstitutionSerializer(serializers.Serializer):
    source_resource_kind = serializers.CharField()
    source_resource_id = serializers.CharField()
    destination_resource_kind = serializers.CharField()
    destination_resource_id = serializers.CharField()


class ResourceTransferWithSubstitutionsSerializer(serializers.Serializer):
    source_team_id = serializers.IntegerField()
    destination_team_id = serializers.IntegerField()
    resource_kind = serializers.CharField()
    resource_id = serializers.CharField()
    substitutions = SubstitutionSerializer(many=True, required=False, default=list)


class ResourceSearchSerializer(serializers.Serializer):
    team_id = serializers.IntegerField()
    resource_kind = serializers.CharField()
    q = serializers.CharField(required=False, default="", allow_blank=True)


class ResourceTransferViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "INTERNAL"

    @action(detail=False, methods=["POST"])
    def preview(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """
        Build the dependency graph for a resource transfer and return it
        along with suggested substitutions from previous transfers.
        """
        user = cast(User, request.user)
        serializer = ResourceTransferRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        source_team = self._get_team_in_org(data["source_team_id"])
        destination_team = self._get_team_in_org(data["destination_team_id"])

        if source_team.pk == destination_team.pk:
            raise exceptions.ValidationError("Source and destination teams must be different")

        resource = self._get_source_resource(data["resource_kind"], data["resource_id"], source_team)

        graph = list(build_resource_duplication_graph(resource, set()))
        dag = dag_sort_duplication_graph(graph)

        self._check_access_controls(user, source_team, destination_team, dag)

        suggested = get_suggested_substitutions(dag, destination_team)
        suggested_map: dict[ResourceTransferKey, ResourceTransferKey] = {}
        for source_key, dest_key in suggested:
            suggested_map[source_key] = dest_key

        resources = []
        for vertex in dag:
            visitor = ResourceTransferVisitor.get_visitor(vertex.model)
            if visitor is None or visitor.is_immutable():
                continue

            entry: dict[str, Any] = {
                "resource_kind": visitor.kind,
                "resource_id": str(vertex.primary_key),
                "display_name": visitor.get_display_name(vertex.source_resource),
                "friendly_kind": visitor.friendly_name,
                "user_facing": visitor.user_facing,
            }

            suggested_dest = suggested_map.get(vertex.key)
            if suggested_dest is not None:
                dest_kind, dest_pk = suggested_dest
                dest_visitor = ResourceTransferVisitor.get_visitor(dest_kind)
                if dest_visitor is not None:
                    try:
                        dest_resource = dest_visitor.get_model().objects.get(pk=dest_pk)
                        entry["suggested_substitution"] = {
                            "resource_kind": dest_kind,
                            "resource_id": str(dest_pk),
                            "display_name": dest_visitor.get_display_name(dest_resource),
                        }
                    except dest_visitor.get_model().DoesNotExist:
                        pass

            resources.append(entry)

        return Response({"resources": resources}, status=status.HTTP_200_OK)

    @action(detail=False, methods=["POST"])
    def transfer(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        user = cast(User, request.user)
        serializer = ResourceTransferWithSubstitutionsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        source_team = self._get_team_in_org(data["source_team_id"])
        destination_team = self._get_team_in_org(data["destination_team_id"])

        if source_team.pk == destination_team.pk:
            raise exceptions.ValidationError("Source and destination teams must be different")

        resource = self._get_source_resource(data["resource_kind"], data["resource_id"], source_team)

        graph = list(build_resource_duplication_graph(resource, set()))
        dag = dag_sort_duplication_graph(graph)

        self._check_access_controls(user, source_team, destination_team, dag)

        substitution_pairs: list[tuple[ResourceTransferKey, ResourceTransferKey]] = [
            (
                (sub["source_resource_kind"], sub["source_resource_id"]),
                (sub["destination_resource_kind"], sub["destination_resource_id"]),
            )
            for sub in data["substitutions"]
        ]

        duplicated = duplicate_resource_to_new_team(resource, destination_team, substitution_pairs)
        mutable_results = [r for r in duplicated if r is not None and not _is_immutable(r)]

        return Response(
            {
                "created_resources": [
                    {
                        "kind": type(r).__name__,
                        "id": str(r.pk),
                        "team_id": destination_team.pk,
                    }
                    for r in mutable_results
                ],
                "count": len(mutable_results),
            },
            status=status.HTTP_201_CREATED,
        )

    @action(detail=False, methods=["POST"])
    def search(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """
        Search for resources of a given kind in a target team. Used by the frontend
        to let users pick an existing resource as a substitution.
        """
        serializer = ResourceSearchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        team = self._get_team_in_org(data["team_id"])
        visitor = ResourceTransferVisitor.get_visitor(data["resource_kind"])

        if visitor is None:
            raise exceptions.ValidationError(f"Unsupported resource kind: {data['resource_kind']}")

        if visitor.is_immutable():
            raise exceptions.ValidationError(f"Cannot search for immutable resource kind: {data['resource_kind']}")

        model = visitor.get_model()
        qs = model.objects.filter(team=team)

        query = data.get("q", "").strip()
        if query:
            filter_kwargs = Q()
            if hasattr(model, "name"):
                filter_kwargs |= Q(name__icontains=query)
            if hasattr(model, "body"):
                filter_kwargs |= Q(body__icontains=query)
            qs = qs.filter(filter_kwargs)

        results = [
            {
                "resource_kind": visitor.kind,
                "resource_id": str(r.pk),
                "display_name": visitor.get_display_name(r),
            }
            for r in qs[:25]
        ]

        return Response({"results": results}, status=status.HTTP_200_OK)

    def _get_team_in_org(self, team_id: int) -> Team:
        try:
            return Team.objects.get(id=team_id, organization_id=self.organization_id)
        except Team.DoesNotExist:
            raise exceptions.ValidationError(f"Team {team_id} not found in this organization")

    def _get_source_resource(self, resource_kind: str, resource_id: str, source_team: Team) -> Any:
        visitor = ResourceTransferVisitor.get_visitor(resource_kind)
        if visitor is None:
            raise exceptions.ValidationError(f"Unsupported resource kind: {resource_kind}")

        if visitor.is_immutable():
            raise exceptions.ValidationError(f"Cannot transfer immutable resource kind: {resource_kind}")

        model = visitor.get_model()
        try:
            return model.objects.get(pk=resource_id, team=source_team)
        except model.DoesNotExist:
            raise exceptions.NotFound(f"{resource_kind} with id {resource_id} not found in source team")

    def _check_access_controls(
        self,
        user: User,
        source_team: Team,
        destination_team: Team,
        dag: tuple[ResourceTransferVertex, ...],
    ) -> None:
        """
        Walk the DAG and verify the user has read access on every resource in the
        source team and write access for every mutable resource type in the
        destination team.
        """
        source_ac = UserAccessControl(user=user, team=source_team)
        dest_ac = UserAccessControl(user=user, team=destination_team)

        dest_resource_types_checked: set[str] = set()

        for vertex in dag:
            visitor = ResourceTransferVisitor.get_visitor(vertex.model)
            if visitor is None or visitor.is_immutable():
                continue

            resource_type = model_to_resource(vertex.source_resource)
            if resource_type is None:
                continue

            if not source_ac.check_access_level_for_object(vertex.source_resource, required_level="viewer"):
                raise exceptions.PermissionDenied(
                    f"You do not have read access to {visitor.kind} {vertex.primary_key} in the source project"
                )

            if resource_type not in dest_resource_types_checked:
                if not dest_ac.check_access_level_for_resource(resource_type, required_level="editor"):
                    raise exceptions.PermissionDenied(
                        f"You do not have write access to {visitor.kind} resources in the destination project"
                    )
                dest_resource_types_checked.add(resource_type)


def _is_immutable(resource: Any) -> bool:
    visitor = ResourceTransferVisitor.get_visitor(resource)
    return visitor is not None and visitor.is_immutable()
