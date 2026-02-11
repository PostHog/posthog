from rest_framework import serializers


class TeamScopedPrimaryKeyRelatedField(serializers.PrimaryKeyRelatedField):
    """Auto-filters queryset by context['team_id']. Fails safe to .none()."""

    scope_field = "team_id"

    def get_queryset(self):
        qs = super().get_queryset()
        if qs is None:
            return qs
        team_id = self.context.get("team_id")
        if team_id:
            return qs.filter(**{self.scope_field: team_id})
        return qs.none()


class OrgScopedPrimaryKeyRelatedField(serializers.PrimaryKeyRelatedField):
    """Auto-filters queryset by organization from context. Fails safe to .none()."""

    scope_field = "team__organization"

    def get_queryset(self):
        qs = super().get_queryset()
        if qs is None:
            return qs
        get_org = self.context.get("get_organization")
        if get_org:
            return qs.filter(**{self.scope_field: get_org()})
        return qs.none()
