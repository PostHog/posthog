from posthog.api.person import PersonViewSet


class EnterprisePersonViewSet(PersonViewSet):
    pass


class LegacyEnterprisePersonViewSet(EnterprisePersonViewSet):
    param_derived_from_user_current_team = "team_id"
