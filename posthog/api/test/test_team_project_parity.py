from posthog.test.base import BaseTest

from rest_framework import viewsets

from posthog.api.project import ProjectBackwardCompatSerializer, ProjectViewSet
from posthog.api.shared import ProjectBackwardCompatBasicSerializer, TeamBasicSerializer
from posthog.api.team import TeamSerializer, TeamViewSet

# /api/projects/ (Project model) is the canonical surface; /api/environments/ (Team model) is the
# backward-compat alias we intend to deprecate and permanently redirect onto /api/projects/. For that
# redirect to be safe, the project surface must be a SUPERSET of the environment surface: every field
# and action a client can reach on /api/environments/ must also exist on /api/projects/.
#
# These allowlists capture the only intentional differences. Anything outside them is drift — most
# likely a field or action added to the Team/environment side without mirroring it onto projects — and
# fails this test loudly so it gets fixed before it reaches clients.

# Fields that legitimately exist only on the project surface (a genuine Project concept, not a Team field).
# is_pending_deletion was added project-side on master; a project-only field is fine for the redirect target.
PROJECT_ONLY_SERIALIZER_FIELDS = {"product_description", "is_pending_deletion"}

# Actions that legitimately exist only on the project surface (operate on the Project, not the Team).
PROJECT_ONLY_ACTIONS = {"change_organization"}


def _serializer_field_names(serializer_class) -> set[str]:
    return set(serializer_class().fields.keys())


def _extra_action_names(viewset_class: type[viewsets.GenericViewSet]) -> set[str]:
    return {action.__name__ for action in viewset_class.get_extra_actions()}


class TestTeamProjectParity(BaseTest):
    def test_detail_serializer_is_a_superset_of_team_serializer(self):
        team_fields = _serializer_field_names(TeamSerializer)
        project_fields = _serializer_field_names(ProjectBackwardCompatSerializer)

        missing_on_project = team_fields - project_fields
        self.assertEqual(
            missing_on_project,
            set(),
            f"/api/environments/ exposes fields that /api/projects/ does not: {sorted(missing_on_project)}. "
            f"Mirror them onto ProjectBackwardCompatSerializer (or the redirect to /api/projects/ would drop them).",
        )

        project_only = project_fields - team_fields
        self.assertEqual(
            project_only,
            PROJECT_ONLY_SERIALIZER_FIELDS,
            f"Unexpected project-only serializer fields: {sorted(project_only - PROJECT_ONLY_SERIALIZER_FIELDS)}. "
            f"If intentional, add them to PROJECT_ONLY_SERIALIZER_FIELDS.",
        )

    def test_list_serializers_are_identical(self):
        team_basic_fields = _serializer_field_names(TeamBasicSerializer)
        project_basic_fields = _serializer_field_names(ProjectBackwardCompatBasicSerializer)
        self.assertEqual(
            team_basic_fields,
            project_basic_fields,
            "List responses diverge between /api/environments/ and /api/projects/. "
            f"Only on environments: {sorted(team_basic_fields - project_basic_fields)}; "
            f"only on projects: {sorted(project_basic_fields - team_basic_fields)}.",
        )

    def test_viewset_actions_are_a_superset_of_team_viewset(self):
        team_actions = _extra_action_names(TeamViewSet)
        project_actions = _extra_action_names(ProjectViewSet)

        missing_on_project = team_actions - project_actions
        self.assertEqual(
            missing_on_project,
            set(),
            f"/api/environments/ exposes actions that /api/projects/ does not: {sorted(missing_on_project)}. "
            f"Mirror them onto ProjectViewSet (or the redirect to /api/projects/ would 404 them).",
        )

        project_only = project_actions - team_actions
        self.assertEqual(
            project_only,
            PROJECT_ONLY_ACTIONS,
            f"Unexpected project-only actions: {sorted(project_only - PROJECT_ONLY_ACTIONS)}. "
            f"If intentional, add them to PROJECT_ONLY_ACTIONS.",
        )

    def test_shared_actions_expose_the_same_http_methods(self):
        # For every action present on both viewsets, the allowed HTTP verbs must match — a GET-only action
        # on one side and GET+PATCH on the other would silently drop writes after the redirect.
        team_actions = {a.__name__: a for a in TeamViewSet.get_extra_actions()}
        project_actions = {a.__name__: a for a in ProjectViewSet.get_extra_actions()}

        mismatches: dict[str, tuple] = {}
        for name in team_actions.keys() & project_actions.keys():
            team_methods = {m.lower() for m in getattr(team_actions[name], "mapping", {})}
            project_methods = {m.lower() for m in getattr(project_actions[name], "mapping", {})}
            if team_methods != project_methods:
                mismatches[name] = (sorted(team_methods), sorted(project_methods))

        self.assertEqual(
            mismatches, {}, f"Shared actions expose different HTTP methods (team vs project): {mismatches}"
        )
