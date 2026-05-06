from django.db.models import Manager, QuerySet

from rest_framework import serializers


class TeamScopedPrimaryKeyRelatedField(serializers.PrimaryKeyRelatedField):
    """Auto-filters queryset by context['team_id']. Fails safe to .none()."""

    scope_field = "team_id"

    def get_queryset(self):
        queryset = getattr(self, "queryset", None)
        if queryset is None:
            return None
        qs = queryset.all() if isinstance(queryset, (QuerySet, Manager)) else queryset
        team_id = self.context.get("team_id")
        if team_id:
            return qs.filter(**{self.scope_field: team_id})
        return qs.none()


class OrgScopedPrimaryKeyRelatedField(serializers.PrimaryKeyRelatedField):
    """Auto-filters queryset by organization from context. Fails safe to .none()."""

    scope_field = "team__organization"

    def get_queryset(self):
        queryset = getattr(self, "queryset", None)
        if queryset is None:
            return None
        qs = queryset.all() if isinstance(queryset, (QuerySet, Manager)) else queryset
        get_org = self.context.get("get_organization")
        if get_org:
            try:
                org = get_org()
            except AttributeError:
                return qs.none()
            return qs.filter(**{self.scope_field: org})
        return qs.none()
