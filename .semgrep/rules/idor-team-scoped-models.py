from django.shortcuts import get_object_or_404

from posthog.models import Action, ChangeRequest, Cohort, Insight, Notebook
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.project import Project
from posthog.models.user_scene_personalisation import UserScenePersonalisation

from ee.models.rbac.role import Role, RoleMembership

# ============================================================
# idor-taint-user-input-to-model-get (ERROR - user input flows to lookup)
# ============================================================


def vulnerable_get_from_request(request):
    cohort_id = request.GET.get("cohort_id")
    # ruleid: idor-taint-user-input-to-model-get, idor-lookup-without-team
    return Cohort.objects.get(pk=cohort_id)


def vulnerable_get_from_kwargs(kwargs):
    action_id = kwargs.get("action_id")
    # ruleid: idor-taint-user-input-to-model-get, idor-lookup-without-team
    return Action.objects.get(id=action_id)


def vulnerable_filter_from_data(request):
    insight_id = request.data.get("insight_id")
    # ruleid: idor-taint-user-input-to-model-get, idor-lookup-without-team
    return Insight.objects.filter(pk=insight_id)


# ok: idor-taint-user-input-to-model-get
def safe_get_with_team(request, team):
    cohort_id = request.GET.get("cohort_id")
    # ok: idor-lookup-without-team
    return Cohort.objects.get(pk=cohort_id, team__project_id=team.project_id)


# ok: idor-taint-user-input-to-model-get
def safe_get_with_team_id(request, team_id):
    cohort_id = request.GET.get("cohort_id")
    # ok: idor-lookup-without-team
    return Cohort.objects.get(pk=cohort_id, team_id=team_id)


# ok: idor-taint-user-input-to-model-get
def safe_filter_with_team(request, team):
    insight_id = request.data.get("insight_id")
    # ok: idor-lookup-without-team
    return Insight.objects.filter(pk=insight_id, team=team)


# ok: idor-taint-user-input-to-model-get
def not_user_input():
    # ruleid: idor-lookup-without-team
    return Cohort.objects.get(pk=123)


# ============================================================
# idor-lookup-without-team (WARNING - pattern rule)
# ============================================================

# ruleid: idor-lookup-without-team
cohort = Cohort.objects.get(pk=cohort_id)

# ruleid: idor-lookup-without-team
action = Action.objects.get(id=action_id)

# ruleid: idor-lookup-without-team
cohort = Cohort.objects.get(pk=cohort_id, deleted=False)

# ok: idor-lookup-without-team
cohort = Cohort.objects.get(pk=cohort_id, team__project_id=team.project_id)

# ok: idor-lookup-without-team
cohort = Cohort.objects.get(pk=cohort_id, team=team)

# ok: idor-lookup-without-team
cohort = Cohort.objects.get(pk=cohort_id, team_id=team_id)

# ok: idor-lookup-without-team
cohort = Cohort.objects.annotate(effective_project_id=1).filter(id=cohort_id, effective_project_id=project_id)

# ok: idor-lookup-without-team
cohort = Cohort.objects.annotate(effective_project_id=1).get(pk=cohort_id, effective_project_id=project_id)

# ok: idor-lookup-without-team
ChangeRequest.objects.select_for_update().get(pk=self.change_request.pk)

# ok: idor-lookup-without-team
Notebook.objects.get(pk=instance.pk)

# ok: idor-lookup-without-team
Notebook.objects.select_for_update().get(pk=instance.id)

# ============================================================
# idor-lookup-without-team (WARNING - pattern rule)
# ============================================================

# ruleid: idor-lookup-without-team
insights = Insight.objects.filter(pk=insight_id)

# ruleid: idor-lookup-without-team
cohorts = Cohort.objects.filter(pk__in=cohort_ids)

# ruleid: idor-lookup-without-team
actions = Action.objects.filter(id=action_id, deleted=False)

# ok: idor-lookup-without-team
insights = Insight.objects.filter(pk=insight_id, team_id=team_id)

# ok: idor-lookup-without-team
cohorts = Cohort.objects.filter(pk__in=cohort_ids, team__project_id=team.project_id)

# ok: idor-lookup-without-team
actions = Action.objects.filter(id=action_id, team=team)

# ============================================================
# idor-lookup-without-team (WARNING - pattern rule)
# ============================================================

# ruleid: idor-lookup-without-team
obj, created = Cohort.objects.get_or_create(name="test")

# ruleid: idor-lookup-without-team
obj, created = Action.objects.update_or_create(name="test", defaults={"deleted": False})

# ok: idor-lookup-without-team
obj, created = Cohort.objects.get_or_create(name="test", team_id=team_id)

# ok: idor-lookup-without-team
obj, created = Action.objects.update_or_create(name="test", team=team, defaults={"deleted": False})

# ok: idor-lookup-without-team
obj, created = Insight.objects.get_or_create(name="test", team__project_id=team.project_id)

# ruleid: idor-lookup-without-team
obj = Cohort.objects.aget_or_create(name="test")

# ok: idor-lookup-without-team
obj = Cohort.objects.aget_or_create(name="test", team_id=team_id)

# ============================================================
# NEW: get_object_or_404 — team-scoped
# ============================================================

# ruleid: idor-lookup-without-team
get_object_or_404(Cohort, pk=cohort_id)

# ruleid: idor-lookup-without-team
get_object_or_404(Action, id=action_id)

# ok: idor-lookup-without-team
get_object_or_404(Cohort, pk=cohort_id, team_id=team_id)

# ok: idor-lookup-without-team
get_object_or_404(Action, id=action_id, team__project_id=team.project_id)

# ok: idor-lookup-without-team
get_object_or_404(Cohort, pk=cohort_id, team=team)


def vulnerable_get_object_or_404_from_request(request):
    cohort_id = request.GET.get("cohort_id")
    # ruleid: idor-taint-user-input-to-model-get, idor-lookup-without-team
    return get_object_or_404(Cohort, pk=cohort_id)


# ok: idor-taint-user-input-to-model-get
def safe_get_object_or_404_with_team(request, team_id):
    cohort_id = request.GET.get("cohort_id")
    # ok: idor-lookup-without-team
    return get_object_or_404(Cohort, pk=cohort_id, team_id=team_id)


# ============================================================
# NEW: select_related/prefetch_related chains — team-scoped
# ============================================================

# ruleid: idor-lookup-without-team
cohort = Cohort.objects.select_related("team").get(pk=cohort_id)

# ruleid: idor-lookup-without-team
cohort = Cohort.objects.prefetch_related("team").get(pk=cohort_id)

# ruleid: idor-lookup-without-team
insights = Insight.objects.select_related("team").filter(pk=insight_id)

# ruleid: idor-lookup-without-team
insights = Insight.objects.prefetch_related("team").filter(id=insight_id)

# ok: idor-lookup-without-team
cohort = Cohort.objects.select_related("team").get(pk=cohort_id, team_id=team_id)

# ok: idor-lookup-without-team
cohort = Cohort.objects.prefetch_related("team").get(pk=cohort_id, team=team)

# ok: idor-lookup-without-team
insights = Insight.objects.select_related("team").filter(pk=insight_id, team__project_id=team.project_id)

# ok: idor-lookup-without-team
insights = Insight.objects.prefetch_related("team").filter(id=insight_id, team_id=team_id)


def vulnerable_select_related_from_request(request):
    cohort_id = request.GET.get("cohort_id")
    # ruleid: idor-taint-user-input-to-model-get, idor-lookup-without-team
    return Cohort.objects.select_related("team").get(pk=cohort_id)


# ok: idor-taint-user-input-to-model-get
def safe_select_related_with_team(request, team_id):
    cohort_id = request.GET.get("cohort_id")
    # ok: idor-lookup-without-team
    return Cohort.objects.select_related("team").get(pk=cohort_id, team_id=team_id)


# ============================================================
# NEW: async aget — team-scoped
# ============================================================

# ruleid: idor-lookup-without-team
cohort = Cohort.objects.aget(pk=cohort_id)

# ruleid: idor-lookup-without-team
action = Action.objects.aget(id=action_id)

# ok: idor-lookup-without-team
cohort = Cohort.objects.aget(pk=cohort_id, team_id=team_id)

# ok: idor-lookup-without-team
action = Action.objects.aget(id=action_id, team=team)

# ruleid: idor-lookup-without-team
cohort = Cohort.objects.select_related("team").aget(pk=cohort_id)

# ruleid: idor-lookup-without-team
cohort = Cohort.objects.prefetch_related("team").aget(pk=cohort_id)

# ok: idor-lookup-without-team
cohort = Cohort.objects.select_related("team").aget(pk=cohort_id, team_id=team_id)

# ok: idor-lookup-without-team
cohort = Cohort.objects.prefetch_related("team").aget(pk=cohort_id, team=team)


def vulnerable_aget_from_request(request):
    cohort_id = request.GET.get("cohort_id")
    # ruleid: idor-taint-user-input-to-model-get, idor-lookup-without-team
    return Cohort.objects.aget(pk=cohort_id)


# ok: idor-taint-user-input-to-model-get
def safe_aget_with_team(request, team_id):
    cohort_id = request.GET.get("cohort_id")
    # ok: idor-lookup-without-team
    return Cohort.objects.aget(pk=cohort_id, team_id=team_id)


# ============================================================
# Methods that should NOT be flagged (exclude, create, etc.)
# ============================================================

# ok: idor-lookup-without-team
Cohort.objects.exclude(id=cohort_id)

# ok: idor-lookup-without-team
Cohort.objects.create(id=cohort_id, name="test")

# ok: idor-lookup-without-team
Cohort.objects.filter(team__project_id=project_id).exclude(id=cohort_id)

# ok: idor-lookup-without-team
Cohort.objects.select_related("team").exclude(id=cohort_id)


# ok: idor-taint-user-input-to-model-get
def safe_exclude_from_request(request):
    cohort_id = request.GET.get("cohort_id")
    # ok: idor-lookup-without-team
    return Cohort.objects.exclude(id=cohort_id)


# ok: idor-taint-user-input-to-model-get
def safe_create_from_request(request):
    cohort_id = request.GET.get("cohort_id")
    # ok: idor-lookup-without-team
    return Cohort.objects.create(id=cohort_id, name="test")


# ============================================================
# Models whose names are superstrings of listed models should NOT match
# ============================================================

# ok: idor-lookup-without-team, idor-taint-user-input-to-model-get
DashboardTile.objects.get(pk=tile_id)

# ok: idor-lookup-without-team, idor-taint-user-input-to-model-get
ActionStep.objects.filter(id=step_id)

# ok: idor-lookup-without-team, idor-taint-user-input-to-model-get
TaggedItem.objects.get(pk=item_id)


# ============================================================
# idor-taint-user-input-to-org-model (ERROR - user input flows to org model lookup)
# ============================================================


def vulnerable_org_get_from_request(request):
    project_id = request.GET.get("project_id")
    # ruleid: idor-taint-user-input-to-org-model, idor-lookup-without-org
    return Project.objects.get(pk=project_id)


def vulnerable_org_get_from_kwargs(kwargs):
    role_id = kwargs.get("role_id")
    # ruleid: idor-taint-user-input-to-org-model, idor-lookup-without-org
    return Role.objects.get(id=role_id)


def vulnerable_org_filter_from_data(request):
    membership_id = request.data.get("membership_id")
    # ruleid: idor-taint-user-input-to-org-model, idor-lookup-without-org
    return RoleMembership.objects.filter(pk=membership_id)


# ok: idor-taint-user-input-to-org-model
def safe_org_get_with_organization(request, organization):
    project_id = request.GET.get("project_id")
    # ok: idor-lookup-without-org
    return Project.objects.get(pk=project_id, organization=organization)


# ok: idor-taint-user-input-to-org-model
def safe_org_get_with_organization_id(request, organization_id):
    role_id = request.GET.get("role_id")
    # ok: idor-lookup-without-org
    return Role.objects.get(pk=role_id, organization_id=organization_id)


# ok: idor-taint-user-input-to-org-model
def safe_org_filter_with_role_organization(request, organization):
    membership_id = request.data.get("membership_id")
    # ok: idor-lookup-without-org
    return RoleMembership.objects.filter(pk=membership_id, role__organization=organization)


# ============================================================
# idor-lookup-without-org (WARNING - pattern rule)
# ============================================================

# ruleid: idor-lookup-without-org
project = Project.objects.get(pk=project_id)

# ruleid: idor-lookup-without-org
role = Role.objects.get(id=role_id)

# ruleid: idor-lookup-without-org
membership = RoleMembership.objects.filter(pk=membership_id)

# ok: idor-lookup-without-org
project = Project.objects.get(pk=project_id, organization=organization)

# ok: idor-lookup-without-org
role = Role.objects.get(id=role_id, organization_id=organization_id)

# ok: idor-lookup-without-org
membership = RoleMembership.objects.filter(pk=membership_id, role__organization=organization)

# ok: idor-lookup-without-org
membership = RoleMembership.objects.filter(pk=membership_id, role__organization_id=organization_id)

# ruleid: idor-lookup-without-org
obj, created = Role.objects.get_or_create(name="test")

# ok: idor-lookup-without-org
obj, created = Role.objects.get_or_create(name="test", organization=organization)

# ruleid: idor-lookup-without-org
obj = Role.objects.aget_or_create(name="test")

# ok: idor-lookup-without-org
obj = Role.objects.aget_or_create(name="test", organization=organization)

# ok: idor-lookup-without-org
Project.objects.get(pk=instance.pk)

# ok: idor-lookup-without-org
Role.objects.select_for_update().get(pk=self.role.id)

# ============================================================
# NEW: get_object_or_404 — org-scoped
# ============================================================

# ruleid: idor-lookup-without-org
get_object_or_404(Project, pk=project_id)

# ok: idor-lookup-without-org
get_object_or_404(Project, pk=project_id, organization=organization)

# ok: idor-lookup-without-org
get_object_or_404(Project, pk=project_id, organization_id=organization_id)

# ok: idor-lookup-without-org
get_object_or_404(RoleMembership, pk=membership_id, role__organization=organization)


def vulnerable_org_get_object_or_404(request):
    project_id = request.GET.get("project_id")
    # ruleid: idor-taint-user-input-to-org-model, idor-lookup-without-org
    return get_object_or_404(Project, pk=project_id)


# ok: idor-taint-user-input-to-org-model
def safe_org_get_object_or_404(request, organization):
    project_id = request.GET.get("project_id")
    # ok: idor-lookup-without-org
    return get_object_or_404(Project, pk=project_id, organization=organization)


# ============================================================
# NEW: select_related/prefetch_related — org-scoped
# ============================================================

# ruleid: idor-lookup-without-org
project = Project.objects.select_related("organization").get(pk=project_id)

# ruleid: idor-lookup-without-org
role = Role.objects.prefetch_related("organization").get(id=role_id)

# ok: idor-lookup-without-org
project = Project.objects.select_related("organization").get(pk=project_id, organization=organization)

# ok: idor-lookup-without-org
role = Role.objects.prefetch_related("organization").get(id=role_id, organization_id=organization_id)


def vulnerable_org_select_related(request):
    project_id = request.GET.get("project_id")
    # ruleid: idor-taint-user-input-to-org-model, idor-lookup-without-org
    return Project.objects.select_related("organization").get(pk=project_id)


# ok: idor-taint-user-input-to-org-model
def safe_org_select_related(request, organization):
    project_id = request.GET.get("project_id")
    # ok: idor-lookup-without-org
    return Project.objects.select_related("organization").get(pk=project_id, organization=organization)


# ============================================================
# NEW: async aget — org-scoped
# ============================================================

# ruleid: idor-lookup-without-org
project = Project.objects.aget(pk=project_id)

# ok: idor-lookup-without-org
project = Project.objects.aget(pk=project_id, organization=organization)

# ruleid: idor-lookup-without-org
project = Project.objects.select_related("organization").aget(pk=project_id)

# ok: idor-lookup-without-org
project = Project.objects.select_related("organization").aget(pk=project_id, organization=organization)


def vulnerable_org_aget(request):
    project_id = request.GET.get("project_id")
    # ruleid: idor-taint-user-input-to-org-model, idor-lookup-without-org
    return Project.objects.aget(pk=project_id)


# ok: idor-taint-user-input-to-org-model
def safe_org_aget(request, organization):
    project_id = request.GET.get("project_id")
    # ok: idor-lookup-without-org
    return Project.objects.aget(pk=project_id, organization=organization)


# ============================================================
# idor-taint-user-input-to-user-model (ERROR - user input flows to user model lookup)
# ============================================================


def vulnerable_user_get_from_request(request):
    key_id = request.GET.get("key_id")
    # ruleid: idor-taint-user-input-to-user-model, idor-lookup-without-user
    return PersonalAPIKey.objects.get(pk=key_id)


def vulnerable_user_filter_from_data(request):
    key_id = request.data.get("key_id")
    # ruleid: idor-taint-user-input-to-user-model, idor-lookup-without-user
    return PersonalAPIKey.objects.filter(id=key_id)


# ok: idor-taint-user-input-to-user-model
def safe_user_get_with_user(request, user):
    key_id = request.GET.get("key_id")
    # ok: idor-lookup-without-user
    return PersonalAPIKey.objects.get(pk=key_id, user=user)


# ok: idor-taint-user-input-to-user-model
def safe_user_get_with_user_id(request, user_id):
    key_id = request.GET.get("key_id")
    # ok: idor-lookup-without-user
    return PersonalAPIKey.objects.get(pk=key_id, user_id=user_id)


# ============================================================
# idor-lookup-without-user (WARNING - pattern rule)
# ============================================================

# ruleid: idor-lookup-without-user
key = PersonalAPIKey.objects.get(pk=key_id)

# ruleid: idor-lookup-without-user
key = PersonalAPIKey.objects.filter(id=key_id)

# ok: idor-lookup-without-user
key = PersonalAPIKey.objects.get(pk=key_id, user=user)

# ok: idor-lookup-without-user
key = PersonalAPIKey.objects.filter(id=key_id, user_id=user_id)

# ruleid: idor-lookup-without-user
obj, created = PersonalAPIKey.objects.get_or_create(label="test")

# ok: idor-lookup-without-user
obj, created = PersonalAPIKey.objects.get_or_create(label="test", user=user)

# ruleid: idor-lookup-without-user
obj = PersonalAPIKey.objects.aget_or_create(label="test")

# ok: idor-lookup-without-user
obj = PersonalAPIKey.objects.aget_or_create(label="test", user=user)

# ok: idor-lookup-without-user
PersonalAPIKey.objects.get(pk=instance.pk)

# ok: idor-lookup-without-user
PersonalAPIKey.objects.select_for_update().get(id=self.key.id)

# ============================================================
# NEW: get_object_or_404 — user-scoped
# ============================================================

# ruleid: idor-lookup-without-user
get_object_or_404(PersonalAPIKey, pk=key_id)

# ok: idor-lookup-without-user
get_object_or_404(PersonalAPIKey, pk=key_id, user=user)

# ok: idor-lookup-without-user
get_object_or_404(PersonalAPIKey, pk=key_id, user_id=user_id)


def vulnerable_user_get_object_or_404(request):
    key_id = request.GET.get("key_id")
    # ruleid: idor-taint-user-input-to-user-model, idor-lookup-without-user
    return get_object_or_404(PersonalAPIKey, pk=key_id)


# ok: idor-taint-user-input-to-user-model
def safe_user_get_object_or_404(request, user):
    key_id = request.GET.get("key_id")
    # ok: idor-lookup-without-user
    return get_object_or_404(PersonalAPIKey, pk=key_id, user=user)


# ============================================================
# NEW: select_related/prefetch_related — user-scoped
# ============================================================

# ruleid: idor-lookup-without-user
key = PersonalAPIKey.objects.select_related("user").get(pk=key_id)

# ok: idor-lookup-without-user
key = PersonalAPIKey.objects.select_related("user").get(pk=key_id, user=user)

# ruleid: idor-lookup-without-user
key = PersonalAPIKey.objects.prefetch_related("user").filter(id=key_id)

# ok: idor-lookup-without-user
key = PersonalAPIKey.objects.prefetch_related("user").filter(id=key_id, user_id=user_id)


def vulnerable_user_select_related(request):
    key_id = request.GET.get("key_id")
    # ruleid: idor-taint-user-input-to-user-model, idor-lookup-without-user
    return PersonalAPIKey.objects.select_related("user").get(pk=key_id)


# ok: idor-taint-user-input-to-user-model
def safe_user_select_related(request, user):
    key_id = request.GET.get("key_id")
    # ok: idor-lookup-without-user
    return PersonalAPIKey.objects.select_related("user").get(pk=key_id, user=user)


# ============================================================
# NEW: async aget — user-scoped
# ============================================================

# ruleid: idor-lookup-without-user
key = PersonalAPIKey.objects.aget(pk=key_id)

# ok: idor-lookup-without-user
key = PersonalAPIKey.objects.aget(pk=key_id, user=user)

# ruleid: idor-lookup-without-user
key = PersonalAPIKey.objects.select_related("user").aget(pk=key_id)

# ok: idor-lookup-without-user
key = PersonalAPIKey.objects.select_related("user").aget(pk=key_id, user_id=user_id)


def vulnerable_user_aget(request):
    key_id = request.GET.get("key_id")
    # ruleid: idor-taint-user-input-to-user-model, idor-lookup-without-user
    return PersonalAPIKey.objects.aget(pk=key_id)


# ok: idor-taint-user-input-to-user-model
def safe_user_aget(request, user):
    key_id = request.GET.get("key_id")
    # ok: idor-lookup-without-user
    return PersonalAPIKey.objects.aget(pk=key_id, user=user)


# ============================================================
# idor-taint-user-input-to-user-team-model (ERROR - user input flows without BOTH filters)
# ============================================================


def vulnerable_user_team_get_from_request(request):
    settings_id = request.GET.get("settings_id")
    # ruleid: idor-taint-user-input-to-user-team-model, idor-lookup-without-user-and-team
    return UserScenePersonalisation.objects.get(pk=settings_id)


def vulnerable_user_team_only_user(request, user):
    settings_id = request.GET.get("settings_id")
    # ruleid: idor-taint-user-input-to-user-team-model, idor-lookup-without-user-and-team
    return UserScenePersonalisation.objects.get(pk=settings_id, user=user)


def vulnerable_user_team_only_team(request, team):
    settings_id = request.GET.get("settings_id")
    # ruleid: idor-taint-user-input-to-user-team-model, idor-lookup-without-user-and-team
    return UserScenePersonalisation.objects.get(pk=settings_id, team=team)


# ok: idor-taint-user-input-to-user-team-model
def safe_user_team_with_both(request, user, team):
    settings_id = request.GET.get("settings_id")
    # ok: idor-lookup-without-user-and-team
    return UserScenePersonalisation.objects.get(pk=settings_id, user=user, team=team)


# ok: idor-taint-user-input-to-user-team-model
def safe_user_team_with_both_ids(request, user_id, team_id):
    settings_id = request.GET.get("settings_id")
    # ok: idor-lookup-without-user-and-team
    return UserScenePersonalisation.objects.get(pk=settings_id, user_id=user_id, team_id=team_id)


# ok: idor-taint-user-input-to-user-team-model
def safe_user_team_reversed_order(request, user, team):
    settings_id = request.GET.get("settings_id")
    # ok: idor-lookup-without-user-and-team
    return UserScenePersonalisation.objects.get(pk=settings_id, team=team, user=user)


# ============================================================
# idor-lookup-without-user-and-team (WARNING - pattern rule)
# ============================================================

# ruleid: idor-lookup-without-user-and-team
settings = UserScenePersonalisation.objects.get(pk=settings_id)

# ruleid: idor-lookup-without-user-and-team
settings = UserScenePersonalisation.objects.get(pk=settings_id, user=user)

# ruleid: idor-lookup-without-user-and-team
settings = UserScenePersonalisation.objects.get(pk=settings_id, team=team)

# ok: idor-lookup-without-user-and-team
settings = UserScenePersonalisation.objects.get(pk=settings_id, user=user, team=team)

# ok: idor-lookup-without-user-and-team
settings = UserScenePersonalisation.objects.get(pk=settings_id, team_id=team_id, user_id=user_id)

# ruleid: idor-lookup-without-user-and-team
obj, created = UserScenePersonalisation.objects.get_or_create(scene="test")

# ruleid: idor-lookup-without-user-and-team
obj, created = UserScenePersonalisation.objects.get_or_create(scene="test", user=user)

# ok: idor-lookup-without-user-and-team
obj, created = UserScenePersonalisation.objects.get_or_create(scene="test", user=user, team=team)

# ruleid: idor-lookup-without-user-and-team
obj = UserScenePersonalisation.objects.aget_or_create(scene="test")

# ok: idor-lookup-without-user-and-team
obj = UserScenePersonalisation.objects.aget_or_create(scene="test", user=user, team=team)

# ok: idor-lookup-without-user-and-team
UserScenePersonalisation.objects.get(pk=instance.pk)

# ok: idor-lookup-without-user-and-team
UserScenePersonalisation.objects.select_for_update().get(id=self.settings.id)

# ============================================================
# NEW: get_object_or_404 — user+team-scoped
# ============================================================

# ruleid: idor-lookup-without-user-and-team
get_object_or_404(UserScenePersonalisation, pk=settings_id)

# ruleid: idor-lookup-without-user-and-team
get_object_or_404(UserScenePersonalisation, pk=settings_id, user=user)

# ruleid: idor-lookup-without-user-and-team
get_object_or_404(UserScenePersonalisation, pk=settings_id, team=team)

# ok: idor-lookup-without-user-and-team
get_object_or_404(UserScenePersonalisation, pk=settings_id, user=user, team=team)

# ok: idor-lookup-without-user-and-team
get_object_or_404(UserScenePersonalisation, pk=settings_id, user_id=user_id, team_id=team_id)


def vulnerable_user_team_get_object_or_404(request):
    settings_id = request.GET.get("settings_id")
    # ruleid: idor-taint-user-input-to-user-team-model, idor-lookup-without-user-and-team
    return get_object_or_404(UserScenePersonalisation, pk=settings_id)


# ok: idor-taint-user-input-to-user-team-model
def safe_user_team_get_object_or_404(request, user, team):
    settings_id = request.GET.get("settings_id")
    # ok: idor-lookup-without-user-and-team
    return get_object_or_404(UserScenePersonalisation, pk=settings_id, user=user, team=team)


# ============================================================
# NEW: select_related/prefetch_related — user+team-scoped
# ============================================================

# ruleid: idor-lookup-without-user-and-team
settings = UserScenePersonalisation.objects.select_related("user", "team").get(pk=settings_id)

# ruleid: idor-lookup-without-user-and-team
settings = UserScenePersonalisation.objects.select_related("user", "team").get(pk=settings_id, user=user)

# ok: idor-lookup-without-user-and-team
settings = UserScenePersonalisation.objects.select_related("user", "team").get(pk=settings_id, user=user, team=team)

# ok: idor-lookup-without-user-and-team
settings = UserScenePersonalisation.objects.prefetch_related("user", "team").get(
    pk=settings_id, team_id=team_id, user_id=user_id
)


def vulnerable_user_team_select_related(request):
    settings_id = request.GET.get("settings_id")
    # ruleid: idor-taint-user-input-to-user-team-model, idor-lookup-without-user-and-team
    return UserScenePersonalisation.objects.select_related("user", "team").get(pk=settings_id)


# ok: idor-taint-user-input-to-user-team-model
def safe_user_team_select_related(request, user, team):
    settings_id = request.GET.get("settings_id")
    # ok: idor-lookup-without-user-and-team
    return UserScenePersonalisation.objects.select_related("user", "team").get(pk=settings_id, user=user, team=team)


# ============================================================
# NEW: async aget — user+team-scoped
# ============================================================

# ruleid: idor-lookup-without-user-and-team
settings = UserScenePersonalisation.objects.aget(pk=settings_id)

# ruleid: idor-lookup-without-user-and-team
settings = UserScenePersonalisation.objects.aget(pk=settings_id, user=user)

# ok: idor-lookup-without-user-and-team
settings = UserScenePersonalisation.objects.aget(pk=settings_id, user=user, team=team)

# ruleid: idor-lookup-without-user-and-team
settings = UserScenePersonalisation.objects.select_related("user").aget(pk=settings_id)

# ok: idor-lookup-without-user-and-team
settings = UserScenePersonalisation.objects.select_related("user").aget(pk=settings_id, user=user, team_id=team_id)


def vulnerable_user_team_aget(request):
    settings_id = request.GET.get("settings_id")
    # ruleid: idor-taint-user-input-to-user-team-model, idor-lookup-without-user-and-team
    return UserScenePersonalisation.objects.aget(pk=settings_id)


# ok: idor-taint-user-input-to-user-team-model
def safe_user_team_aget(request, user, team):
    settings_id = request.GET.get("settings_id")
    # ok: idor-lookup-without-user-and-team
    return UserScenePersonalisation.objects.aget(pk=settings_id, user=user, team=team)
