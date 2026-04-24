import copy
from typing import cast

import structlog
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.response import Response

from posthog.api.cohort import CohortSerializer
from posthog.api.documentation import _FallbackSerializer, extend_schema
from posthog.api.feature_flag import FeatureFlagSerializer
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.api.utils import action
from posthog.helpers.encrypted_flag_payloads import get_decrypted_flag_payloads
from posthog.models import FeatureFlag, Team
from posthog.models.cohort import Cohort, CohortOrEmpty
from posthog.models.feature_flag.flag_analytics import get_cached_evaluations_7d_by_team
from posthog.models.filters.filter import Filter
from posthog.models.scheduled_change import ScheduledChange
from posthog.user_permissions import UserPermissions


class CopyFlagsRequestSerializer(serializers.Serializer):
    feature_flag_key = serializers.CharField(required=True, help_text="Key of the feature flag to copy")
    from_project = serializers.IntegerField(required=True, help_text="Source project ID to copy the flag from")
    target_project_ids = serializers.ListField(
        child=serializers.IntegerField(),
        required=True,
        max_length=50,
        help_text="List of target project IDs to copy the flag to",
    )
    copy_schedule = serializers.BooleanField(
        required=False,
        default=False,
        help_text="Whether to also copy scheduled changes for this flag",
    )


class CopyFlagsResultSerializer(serializers.Serializer):
    project_id = serializers.IntegerField(required=False, help_text="Project ID (present on failure)")
    error_message = serializers.CharField(required=False, help_text="Error message (present on failure)")


class CopyFlagsSuccessItemSerializer(serializers.Serializer):
    id = serializers.IntegerField(help_text="ID of the created feature flag")
    key = serializers.CharField(help_text="Key of the feature flag")
    name = serializers.CharField(help_text="Name of the feature flag")
    active = serializers.BooleanField(help_text="Whether the flag is active")
    team_id = serializers.IntegerField(help_text="Team ID the flag was copied to")


class CopyFlagsResponseSerializer(serializers.Serializer):
    success = CopyFlagsSuccessItemSerializer(many=True, help_text="List of successfully copied flags")
    failed = CopyFlagsResultSerializer(many=True, help_text="List of failed copy attempts")


logger = structlog.get_logger(__name__)


class OrganizationFeatureFlagView(
    TeamAndOrgViewSetMixin,
    viewsets.ViewSet,
    mixins.RetrieveModelMixin,
):
    scope_object = "INTERNAL"
    serializer_class = _FallbackSerializer
    """
    Retrieves all feature flags for a given organization and key.
    """

    lookup_field = "feature_flag_key"

    @extend_schema(
        operation_id="org_feature_flags_retrieve",
        parameters=[OpenApiParameter("feature_flag_key", OpenApiTypes.STR, OpenApiParameter.PATH)],
    )
    def retrieve(self, request, *args, **kwargs):
        feature_flag_key = kwargs.get(self.lookup_field)

        # Only return flags from teams the user has access to
        user_permissions = UserPermissions(user=request.user)
        accessible_team_ids = user_permissions.team_ids_visible_for_user
        org_team_ids = set(self.organization.teams.values_list("id", flat=True))
        team_ids = list(org_team_ids & set(accessible_team_ids))

        flags = FeatureFlag.objects.filter(
            key=feature_flag_key,
            team_id__in=team_ids,
        )

        counts_by_team = get_cached_evaluations_7d_by_team(
            cast(str, feature_flag_key), [flag.team_id for flag in flags]
        )

        flags_data = [
            {
                "flag_id": flag.id,
                "team_id": flag.team_id,
                "created_by": UserBasicSerializer(flag.created_by).data
                if hasattr(flag, "created_by") and flag.created_by
                else None,
                "filters": flag.get_filters(),
                "created_at": flag.created_at,
                "active": flag.active,
                "evaluations_7d": counts_by_team.get(flag.team_id) if counts_by_team is not None else None,
            }
            for flag in flags
        ]

        return Response(flags_data)

    @extend_schema(
        request=CopyFlagsRequestSerializer,
        responses={200: CopyFlagsResponseSerializer},
    )
    @action(detail=False, methods=["post"], url_path="copy_flags")
    def copy_flags(self, request, *args, **kwargs):
        body = request.data
        feature_flag_key = body.get("feature_flag_key")
        from_project = body.get("from_project")
        target_project_ids = body.get("target_project_ids")
        copy_schedule = body.get("copy_schedule", False)  # Optional parameter to copy schedules

        if not feature_flag_key or not from_project or not target_project_ids:
            return Response({"error": "Missing required fields"}, status=status.HTTP_400_BAD_REQUEST)

        # Fetch the flag to copy
        try:
            flag_to_copy = FeatureFlag.objects.get(
                key=feature_flag_key,
                team__project_id=from_project,
                team__organization_id=self.organization_id,
            )
        except FeatureFlag.DoesNotExist:
            return Response({"error": "Feature flag to copy does not exist."}, status=status.HTTP_400_BAD_REQUEST)

        # Check if the user is allowed to edit the flag using new access control
        from posthog.rbac.user_access_control import UserAccessControl, access_level_satisfied_for_resource

        user_access_control = UserAccessControl(request.user, flag_to_copy.team)
        user_access_level = user_access_control.get_user_access_level(flag_to_copy)

        if not user_access_level or not access_level_satisfied_for_resource(
            "feature_flag", user_access_level, "editor"
        ):
            return Response(
                {"error": "You do not have permission to copy this flag."}, status=status.HTTP_403_FORBIDDEN
            )

        successful_projects = []
        failed_projects = []

        # Get accessible teams for the user
        user_permissions = UserPermissions(user=request.user)
        accessible_team_ids = set(user_permissions.team_ids_visible_for_user)

        for target_project_id in target_project_ids:
            target_team = Team.objects.filter(project_id=target_project_id).first()
            if target_team is None or target_team.id not in accessible_team_ids:
                failed_projects.append(
                    {
                        "project_id": target_project_id,
                        "error_message": "Project not found.",
                    }
                )
                continue

            # get all linked cohorts, sorted by creation order
            seen_cohorts_cache: dict[int, CohortOrEmpty] = {}
            sorted_cohort_ids = flag_to_copy.get_cohort_ids(
                seen_cohorts_cache=seen_cohorts_cache, sort_by_topological_order=True
            )

            # Also include cohorts from scheduled changes if copying schedules
            # Fetch schedules once and reuse for both cohort extraction and copying
            source_schedules = []
            if copy_schedule:
                source_schedules = list(
                    ScheduledChange.objects.filter(
                        record_id=str(flag_to_copy.id),
                        model_name=ScheduledChange.AllowedModels.FEATURE_FLAG,
                        executed_at__isnull=True,
                        team=flag_to_copy.team,
                    )
                )
                schedule_cohort_ids = self._extract_cohort_ids_from_schedules(source_schedules)
                for cohort_id in schedule_cohort_ids:
                    if cohort_id not in seen_cohorts_cache:
                        cohort = Cohort.objects.filter(id=cohort_id, team=flag_to_copy.team, deleted=False).first()
                        if cohort:
                            seen_cohorts_cache[cohort_id] = cohort
                            sorted_cohort_ids.append(cohort_id)

            # Cohorts are mapped by name because IDs differ across projects. This is fragile
            # if cohort names change or aren't unique, but it's the only identifier we can use
            # to match cohorts across projects.
            # destination cohort id is different from original cohort id - create mapping
            name_to_dest_cohort_id: dict[str, int] = {}
            # create cohorts in the destination project
            if len(sorted_cohort_ids):
                for cohort_id in sorted_cohort_ids:
                    original_cohort = seen_cohorts_cache[cohort_id]

                    if not original_cohort:
                        continue

                    # search in destination project by name
                    destination_cohort = Cohort.objects.filter(
                        name=original_cohort.name, team__project_id=target_project_id, deleted=False
                    ).first()

                    # create new cohort in the destination project
                    if not destination_cohort:
                        prop_group = Filter(
                            data={"properties": original_cohort.properties.to_dict(), "is_simplified": True}
                        ).property_groups

                        for prop in prop_group.flat:
                            if prop.type == "cohort" and not isinstance(prop.value, list):
                                try:
                                    original_child_cohort_id = int(prop.value)
                                    original_child_cohort = seen_cohorts_cache[original_child_cohort_id]

                                    if not original_child_cohort or original_child_cohort.name is None:
                                        continue
                                    prop.value = name_to_dest_cohort_id[original_child_cohort.name]
                                except (ValueError, TypeError):
                                    continue

                        destination_cohort_serializer = CohortSerializer(
                            data={
                                "team": target_team,
                                "name": original_cohort.name,
                                "groups": [],
                                "filters": {"properties": prop_group.to_dict()},
                                "description": original_cohort.description,
                                "is_static": original_cohort.is_static,
                            },
                            context={
                                "request": request,
                                "team_id": target_team.id,
                            },
                        )
                        destination_cohort_serializer.is_valid(raise_exception=True)
                        destination_cohort = destination_cohort_serializer.save()

                    if destination_cohort is not None and original_cohort.name is not None:
                        name_to_dest_cohort_id[original_cohort.name] = destination_cohort.id

            # reference correct destination cohort ids in the flag
            for group in flag_to_copy.conditions:
                props = group.get("properties", [])
                for prop in props:
                    if isinstance(prop, dict) and prop.get("type") == "cohort":
                        try:
                            original_cohort_id = int(prop["value"])
                            original_cohort_ref = seen_cohorts_cache[original_cohort_id]
                            if not original_cohort_ref or original_cohort_ref.name is None:
                                continue
                            cohort_name = original_cohort_ref.name
                            prop["value"] = name_to_dest_cohort_id[cohort_name]
                        except (ValueError, TypeError):
                            continue

            # Retrieve filters per iteration since cohort replacement logic mutates the dict
            filters = flag_to_copy.get_filters()
            if flag_to_copy.has_encrypted_payloads:
                # Decrypt payloads before copying to ensure the new flag has unencrypted payloads
                # that will be re-encrypted by the serializer if needed
                encrypted_payloads = filters.get("payloads", {})
                filters["payloads"] = get_decrypted_flag_payloads(encrypted_payloads, should_decrypt=True)

            flag_data = {
                "key": flag_to_copy.key,
                "name": flag_to_copy.name,
                "filters": filters,
                "active": flag_to_copy.active,
                "ensure_experience_continuity": flag_to_copy.ensure_experience_continuity,
                "deleted": False,
                "evaluation_runtime": flag_to_copy.evaluation_runtime,
                "bucketing_identifier": flag_to_copy.bucketing_identifier,
                "is_remote_configuration": flag_to_copy.is_remote_configuration,
                "has_encrypted_payloads": flag_to_copy.has_encrypted_payloads,
            }
            existing_flag = FeatureFlag.objects.filter(key=feature_flag_key, team__project_id=target_project_id).first()

            context = {
                "request": request,
                "team_id": target_project_id,
                "project_id": target_project_id,
            }

            # Set method to PATCH for updates, POST for new creations
            # This ensures proper validation scoping for feature flag creation
            if existing_flag:
                request.method = "PATCH"
                feature_flag_serializer = FeatureFlagSerializer(
                    existing_flag, data=flag_data, partial=True, context=context
                )
            # Create new flag
            else:
                request.method = "POST"
                feature_flag_serializer = FeatureFlagSerializer(data=flag_data, context=context)

            try:
                feature_flag_serializer.is_valid(raise_exception=True)
                saved_flag = feature_flag_serializer.save(team_id=target_project_id)

                # Copy schedules if requested
                schedule_copy_error = None
                if copy_schedule:
                    try:
                        self._copy_feature_flag_schedules(
                            source_schedules,
                            saved_flag,
                            request.user,
                            name_to_dest_cohort_id,
                            seen_cohorts_cache,
                        )
                    except Exception as e:
                        logger.exception(
                            "Failed to copy feature flag schedules",
                            source_flag_id=flag_to_copy.id,
                            target_flag_id=saved_flag.id,
                        )
                        schedule_copy_error = str(e)

                result = feature_flag_serializer.data
                if schedule_copy_error:
                    result["schedule_copy_warning"] = f"Flag copied but schedules failed: {schedule_copy_error}"
                successful_projects.append(result)
            except Exception as e:
                failed_projects.append(
                    {
                        "project_id": target_project_id,
                        "error_message": str(e)
                        if not feature_flag_serializer.errors
                        else feature_flag_serializer.errors,
                    }
                )

        return Response(
            {"success": successful_projects, "failed": failed_projects},
            status=status.HTTP_200_OK,
        )

    def _copy_feature_flag_schedules(self, source_schedules, target_flag, user, cohort_mapping, cohort_cache):
        """
        Copy all scheduled changes from source flag to target flag.

        Args:
            source_schedules: List of ScheduledChange objects to copy (already fetched)
            target_flag: The newly created/updated FeatureFlag instance
            user: The user performing the copy operation
            cohort_mapping: Dict mapping source cohort names to target cohort IDs
            cohort_cache: Dict of cohort_id -> Cohort objects to avoid N+1 queries
        """
        from posthog.rbac.user_access_control import UserAccessControl, access_level_satisfied_for_resource

        # Validate user has permission to create schedules in target project
        user_access_control = UserAccessControl(user, target_flag.team)
        user_access_level = user_access_control.get_user_access_level(target_flag)

        if not user_access_level or not access_level_satisfied_for_resource(
            "feature_flag", user_access_level, "editor"
        ):
            # Skip copying schedules if user lacks permissions, don't fail the entire operation
            return

        # Copy each schedule to the target flag
        for schedule in source_schedules:
            # Remap cohort IDs in schedule payload
            updated_payload = self._remap_cohort_ids_in_payload(schedule.payload, cohort_mapping, cohort_cache)

            ScheduledChange.objects.create(
                record_id=str(target_flag.id),
                model_name=ScheduledChange.AllowedModels.FEATURE_FLAG,
                payload=updated_payload,
                scheduled_at=schedule.scheduled_at,
                is_recurring=schedule.is_recurring,
                recurrence_interval=schedule.recurrence_interval,
                end_date=schedule.end_date,
                team=target_flag.team,
                created_by=user,
            )

    def _remap_cohort_ids_in_payload(self, payload, cohort_mapping, cohort_cache):
        """Remap cohort IDs in schedule payload to target project cohorts."""
        updated_payload = copy.deepcopy(payload)

        # Handle filters in payload (for AddReleaseCondition operations)
        if "filters" in updated_payload and "groups" in updated_payload["filters"]:
            for group in updated_payload["filters"]["groups"]:
                for prop in group.get("properties", []):
                    if isinstance(prop, dict) and prop.get("type") == "cohort":
                        try:
                            original_cohort_id = int(prop["value"])
                            # Use cached cohort instead of querying database
                            source_cohort = cohort_cache.get(original_cohort_id)
                            if source_cohort and source_cohort.name in cohort_mapping:
                                prop["value"] = cohort_mapping[source_cohort.name]
                        except (ValueError, TypeError):
                            continue

        return updated_payload

    def _extract_cohort_ids_from_schedules(self, schedules):
        """Extract all cohort IDs referenced in pending scheduled changes."""
        cohort_ids = set()

        for schedule in schedules:
            payload = schedule.payload
            # Check for cohorts in AddReleaseCondition operations
            if "filters" in payload and "groups" in payload["filters"]:
                for group in payload["filters"]["groups"]:
                    for prop in group.get("properties", []):
                        if isinstance(prop, dict) and prop.get("type") == "cohort":
                            try:
                                cohort_id = int(prop["value"])
                                cohort_ids.add(cohort_id)
                            except (ValueError, TypeError):
                                continue

        return list(cohort_ids)
