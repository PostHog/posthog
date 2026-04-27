"""Unit tests for `fk_discovery.discover_writable_tenant_fks`.

We use real Django models from posthog (Dashboard, Insight, Cohort,
FeatureFlag, Integration) so the discovery walks production-shaped
serializers — but the test serializers themselves are defined inline so
we don't depend on real product code.

The discovery walks serializer field metadata only; it does not query
the DB, so these tests don't need `@pytest.mark.django_db`.
"""

from __future__ import annotations

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, viewsets
from rest_framework.decorators import action

from posthog.api.scoped_related_fields import OrgScopedPrimaryKeyRelatedField, TeamScopedPrimaryKeyRelatedField
from posthog.models.cohort import Cohort
from posthog.models.feature_flag.feature_flag import FeatureFlag
from posthog.models.insight import Insight
from posthog.models.integration import Integration
from posthog.models.user import User
from posthog.test.idor.fk_discovery import (
    FilterParam,
    discover_action_serializers,
    discover_filter_params,
    discover_writable_tenant_fks,
)

from products.dashboards.backend.models.dashboard import Dashboard


class _PlainSerializer(serializers.ModelSerializer):
    dashboard = serializers.PrimaryKeyRelatedField(queryset=Dashboard.objects.all(), required=False, allow_null=True)

    class Meta:
        model = Insight
        fields = ["id", "name", "dashboard"]


class _ScopedSerializer(serializers.ModelSerializer):
    dashboard = TeamScopedPrimaryKeyRelatedField(queryset=Dashboard.objects.all(), required=False, allow_null=True)

    class Meta:
        model = Insight
        fields = ["id", "name", "dashboard"]


class _ReadOnlyFKSerializer(serializers.ModelSerializer):
    dashboard = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = Insight
        fields = ["id", "name", "dashboard"]


class _ReadOnlyFieldsMetaSerializer(serializers.ModelSerializer):
    """Auto-generated `dashboard` field; `read_only_fields` makes it read-only."""

    class Meta:
        model = Insight
        fields = ["id", "name", "dashboard"]
        read_only_fields = ["dashboard"]


class _NonTenantFKSerializer(serializers.ModelSerializer):
    """Reference to a non-tenant-scoped model (User globally) should be skipped."""

    created_by = serializers.PrimaryKeyRelatedField(queryset=User.objects.all(), required=False, allow_null=True)

    class Meta:
        model = Insight
        fields = ["id", "name", "created_by"]


class _MultiFKSerializer(serializers.ModelSerializer):
    feature_flag = serializers.PrimaryKeyRelatedField(queryset=FeatureFlag.objects.all())
    cohort = serializers.PrimaryKeyRelatedField(queryset=Cohort.objects.all())

    class Meta:
        model = Insight
        fields = ["id", "feature_flag", "cohort"]


class _NestedDestinationSerializer(serializers.ModelSerializer):
    integration = serializers.PrimaryKeyRelatedField(queryset=Integration.objects.all())

    class Meta:
        model = Integration
        fields = ["id", "integration"]


class _ParentWithNestedSerializer(serializers.ModelSerializer):
    destination = _NestedDestinationSerializer()

    class Meta:
        model = Insight
        fields = ["id", "destination"]


class _OrgScopedSerializer(serializers.ModelSerializer):
    integration = OrgScopedPrimaryKeyRelatedField(queryset=Integration.objects.all())

    class Meta:
        model = Insight
        fields = ["id", "integration"]


class _ImplicitIntegerIdSerializer(serializers.ModelSerializer):
    """The classic AnnotationSerializer shape — `<thing>_id = IntegerField()`."""

    dashboard_id = serializers.IntegerField(required=False, allow_null=True)

    class Meta:
        # Annotation has a `dashboard` ForeignKey that auto-populates `dashboard_id`.
        from posthog.models.annotation import Annotation as _Annotation

        model = _Annotation
        fields = ["id", "dashboard_id"]


class _ImplicitNonFKIntegerSerializer(serializers.ModelSerializer):
    """`order_id` looks FK-shaped but the model has no `order` ForeignKey — must NOT match."""

    order_id = serializers.IntegerField()

    class Meta:
        model = Insight
        fields = ["id", "order_id"]


class _ImplicitIdToNonTenantSerializer(serializers.ModelSerializer):
    """`created_by_id` — User isn't tenant-scoped — must NOT match."""

    created_by_id = serializers.IntegerField()

    class Meta:
        model = Insight
        fields = ["id", "created_by_id"]


class _ManyRelatedUnscopedSerializer(serializers.ModelSerializer):
    """Vulnerable many=True: queryset isn't tenant-scoped at the single-item level."""

    related_dashboards = serializers.PrimaryKeyRelatedField(many=True, queryset=Dashboard.objects.all(), required=False)

    class Meta:
        model = Insight
        fields = ["id", "related_dashboards"]


class _ManyRelatedScopedSerializer(serializers.ModelSerializer):
    related_dashboards = TeamScopedPrimaryKeyRelatedField(many=True, queryset=Dashboard.objects.all(), required=False)

    class Meta:
        model = Insight
        fields = ["id", "related_dashboards"]


class _ManyRelatedReadOnlySerializer(serializers.ModelSerializer):
    related_dashboards = serializers.PrimaryKeyRelatedField(many=True, read_only=True)

    class Meta:
        model = Insight
        fields = ["id", "related_dashboards"]


class _NestedManyRelatedSerializer(serializers.ModelSerializer):
    """Inner ModelSerializer carrying a writable many=True PK field."""

    related_dashboards = serializers.PrimaryKeyRelatedField(many=True, queryset=Dashboard.objects.all(), required=False)

    class Meta:
        model = Integration
        fields = ["id", "related_dashboards"]


class _ParentWithNestedManyRelatedSerializer(serializers.ModelSerializer):
    destination = _NestedManyRelatedSerializer()

    class Meta:
        model = Insight
        fields = ["id", "destination"]


class _DeepInnerSerializer(serializers.ModelSerializer):
    dashboard = serializers.PrimaryKeyRelatedField(queryset=Dashboard.objects.all())

    class Meta:
        model = Integration
        fields = ["id", "dashboard"]


class _DeepMiddleSerializer(serializers.ModelSerializer):
    config = _DeepInnerSerializer()

    class Meta:
        model = Integration
        fields = ["id", "config"]


class _DeepOuterSerializer(serializers.ModelSerializer):
    """Three-level nesting: outer.middle.inner.dashboard — verifies MAX_NESTING=3 reach."""

    destination = _DeepMiddleSerializer()

    class Meta:
        model = Insight
        fields = ["id", "destination"]


class _SelfReferentialSerializer(serializers.ModelSerializer):
    """Self-recursive nesting — visited-set must terminate the walk without recursion."""

    class Meta:
        model = Insight
        fields = ["id", "child"]


_SelfReferentialSerializer._declared_fields["child"] = _SelfReferentialSerializer()


class TestDiscoverWritableTenantFks:
    def test_plain_pk_field_classified_team_scoped_unscoped(self) -> None:
        result = discover_writable_tenant_fks(_PlainSerializer)
        assert len(result) == 1
        fk = result[0]
        assert fk.serializer_field_name == "dashboard"
        assert fk.target_model is Dashboard
        assert fk.scope == "team"
        assert fk.is_already_scoped is False
        assert fk.nested_path == ()

    def test_team_scoped_pk_field_marked_already_scoped(self) -> None:
        result = discover_writable_tenant_fks(_ScopedSerializer)
        assert len(result) == 1
        assert result[0].is_already_scoped is True
        assert result[0].scope == "team"

    def test_read_only_field_skipped(self) -> None:
        assert discover_writable_tenant_fks(_ReadOnlyFKSerializer) == []

    def test_read_only_fields_meta_marked_create_only(self) -> None:
        result = discover_writable_tenant_fks(_ReadOnlyFieldsMetaSerializer)
        assert len(result) == 1
        fk = result[0]
        assert fk.serializer_field_name == "dashboard"
        assert fk.target_model is Dashboard
        assert fk.is_create_only is True

    def test_deep_nested_serializer_reaches_two_levels(self) -> None:
        result = discover_writable_tenant_fks(_DeepOuterSerializer)
        deep = [fk for fk in result if fk.serializer_field_name == "dashboard"]
        assert len(deep) == 1
        assert deep[0].nested_path == ("destination", "config")
        assert deep[0].target_model is Dashboard

    def test_self_referential_serializer_terminates(self) -> None:
        # Should not infinite-recurse; visited-set blocks repeat entry.
        result = discover_writable_tenant_fks(_SelfReferentialSerializer)
        assert isinstance(result, list)

    def test_recurses_into_plain_serializer_subclass(self) -> None:
        """Plain `serializers.Serializer` nested fields are walked the same as
        ModelSerializer ones — name-pattern detection picks up FKs without
        needing a parent Meta.model. Mirrors the production
        EvaluationSerializer.model_configuration.provider_key_id shape."""
        from products.dashboards.backend.models.dashboard import Dashboard as _Dashboard

        class _InnerNonModelSerializer(serializers.Serializer):
            dashboard_id = serializers.IntegerField(required=False, allow_null=True)

        class _OuterModelSerializer(serializers.ModelSerializer):
            inner = _InnerNonModelSerializer(required=False)

            class Meta:
                model = Insight
                fields = ["id", "inner"]

        result = discover_writable_tenant_fks(_OuterModelSerializer)
        nested = [fk for fk in result if fk.nested_path == ("inner",)]
        assert len(nested) == 1
        assert nested[0].serializer_field_name == "dashboard_id"
        assert nested[0].target_model is _Dashboard
        assert nested[0].is_name_pattern is True

    def test_non_tenant_target_skipped(self) -> None:
        assert discover_writable_tenant_fks(_NonTenantFKSerializer) == []

    def test_multiple_fks_all_returned(self) -> None:
        names = {fk.serializer_field_name for fk in discover_writable_tenant_fks(_MultiFKSerializer)}
        assert names == {"feature_flag", "cohort"}

    def test_nested_serializer_one_level_deep(self) -> None:
        result = discover_writable_tenant_fks(_ParentWithNestedSerializer)
        nested = [fk for fk in result if fk.nested_path]
        assert len(nested) == 1
        assert nested[0].serializer_field_name == "integration"
        assert nested[0].nested_path == ("destination",)
        assert nested[0].target_model is Integration

    def test_org_scoped_field_marked_already_scoped(self) -> None:
        result = discover_writable_tenant_fks(_OrgScopedSerializer)
        assert len(result) == 1
        assert result[0].is_already_scoped is True

    def test_unimportable_serializer_returns_empty(self) -> None:
        class _Broken(serializers.Serializer):
            def get_fields(self) -> dict:  # type: ignore[override]
                raise RuntimeError("intentional")

        assert discover_writable_tenant_fks(_Broken) == []

    def test_implicit_integer_id_to_tenant_model_is_flagged(self) -> None:
        from products.dashboards.backend.models.dashboard import Dashboard as _Dashboard

        result = discover_writable_tenant_fks(_ImplicitIntegerIdSerializer)
        assert len(result) == 1
        fk = result[0]
        assert fk.serializer_field_name == "dashboard_id"
        assert fk.target_model is _Dashboard
        assert fk.scope == "team"
        assert fk.is_implicit is True
        assert fk.is_already_scoped is False

    def test_implicit_id_with_no_matching_fk_is_skipped(self) -> None:
        # Insight has no `order` ForeignKey, so `order_id` is just a number.
        assert discover_writable_tenant_fks(_ImplicitNonFKIntegerSerializer) == []

    def test_implicit_id_to_non_tenant_model_is_skipped(self) -> None:
        # Insight.created_by → User globally; not a tenant-scoped target.
        assert discover_writable_tenant_fks(_ImplicitIdToNonTenantSerializer) == []

    def test_name_pattern_matches_on_non_model_serializer(self) -> None:
        """The tom/dashboard-template shape — `serializers.Serializer` subclass.

        `template` matches three tenant-scoped models (DashboardTemplate,
        HogFlowTemplate, MessageTemplate) by suffix; the discovery emits
        one record per candidate and the runtime test fans out.
        """
        from products.dashboards.backend.models.dashboard_templates import DashboardTemplate

        class _CopyTemplateSerializer(serializers.Serializer):
            source_template_id = serializers.UUIDField(required=True)

        result = discover_writable_tenant_fks(_CopyTemplateSerializer)
        assert len(result) >= 1, f"expected at least 1 name-pattern match, got {result}"
        for fk in result:
            assert fk.serializer_field_name == "source_template_id"
            assert fk.is_name_pattern is True
            assert fk.is_implicit is True
            assert fk.is_already_scoped is False
            assert fk.scope == "team"
        # DashboardTemplate is one of the candidates.
        target_models = {fk.target_model for fk in result}
        assert DashboardTemplate in target_models

    def test_name_pattern_matches_exact_pascal(self) -> None:
        from posthog.models.feature_flag.feature_flag import FeatureFlag

        class _PlainBodySerializer(serializers.Serializer):
            feature_flag_id = serializers.IntegerField(required=True)

        result = discover_writable_tenant_fks(_PlainBodySerializer)
        assert len(result) == 1
        assert result[0].target_model is FeatureFlag

    def test_name_pattern_unknown_thing_is_skipped(self) -> None:
        class _UnknownThingSerializer(serializers.Serializer):
            widget_id = serializers.IntegerField(required=True)

        assert discover_writable_tenant_fks(_UnknownThingSerializer) == []

    def test_name_pattern_ignores_just_id_field(self) -> None:
        class _JustIdSerializer(serializers.Serializer):
            id = serializers.IntegerField(required=True)

        assert discover_writable_tenant_fks(_JustIdSerializer) == []

    def test_name_pattern_short_id_suffix(self) -> None:
        """`<thing>_short_id` should be detected with `lookup_attr=short_id`."""

        class _ShortIdBody(serializers.Serializer):
            dashboard_short_id = serializers.CharField(required=True)

        result = discover_writable_tenant_fks(_ShortIdBody)
        assert len(result) == 1
        fk = result[0]
        assert fk.serializer_field_name == "dashboard_short_id"
        assert fk.lookup_attr == "short_id"
        assert fk.is_name_pattern is True

    def test_name_pattern_key_suffix(self) -> None:
        """`<thing>_key` should be detected with `lookup_attr=key`."""
        from posthog.models.feature_flag.feature_flag import FeatureFlag

        class _KeyBody(serializers.Serializer):
            feature_flag_key = serializers.CharField(required=True)

        result = discover_writable_tenant_fks(_KeyBody)
        assert len(result) == 1
        fk = result[0]
        assert fk.serializer_field_name == "feature_flag_key"
        assert fk.lookup_attr == "key"
        assert fk.target_model is FeatureFlag

    def test_name_pattern_id_default_lookup_attr(self) -> None:
        from products.dashboards.backend.models.dashboard import Dashboard as _Dashboard

        class _IdBody(serializers.Serializer):
            dashboard_id = serializers.IntegerField(required=True)

        result = discover_writable_tenant_fks(_IdBody)
        assert len(result) == 1
        assert result[0].lookup_attr == "pk"
        assert result[0].target_model is _Dashboard

    def test_bulk_ids_listfield_detected(self) -> None:
        """`cohort_ids = ListField(child=IntegerField())` should match Cohort with is_many=True."""
        from posthog.models.cohort.cohort import Cohort

        class _BulkBody(serializers.Serializer):
            cohort_ids = serializers.ListField(child=serializers.IntegerField())

        result = discover_writable_tenant_fks(_BulkBody)
        assert len(result) >= 1
        cohort_records = [fk for fk in result if fk.target_model is Cohort]
        assert len(cohort_records) == 1
        fk = cohort_records[0]
        assert fk.is_many is True
        assert fk.is_implicit is True
        assert fk.is_name_pattern is True

    def test_bulk_ids_unknown_thing_skipped(self) -> None:
        class _UnknownBulk(serializers.Serializer):
            widget_ids = serializers.ListField(child=serializers.IntegerField())

        assert discover_writable_tenant_fks(_UnknownBulk) == []

    def test_plain_ids_field_skipped(self) -> None:
        """`ids = ListField(...)` (no `<thing>` prefix) should not match — too ambiguous."""

        class _PlainBulk(serializers.Serializer):
            ids = serializers.ListField(child=serializers.IntegerField())

        assert discover_writable_tenant_fks(_PlainBulk) == []

    def test_name_pattern_on_modelserializer_falls_back_when_no_fk(self) -> None:
        """Insight has no `template` FK, but `template_id` should still match
        the tenant-scoped *Template models by name pattern."""
        from products.dashboards.backend.models.dashboard_templates import DashboardTemplate

        class _MixedSerializer(serializers.ModelSerializer):
            template_id = serializers.UUIDField(required=True)

            class Meta:
                model = Insight
                fields = ["id", "template_id"]

        result = discover_writable_tenant_fks(_MixedSerializer)
        template_records = [fk for fk in result if fk.serializer_field_name == "template_id"]
        assert template_records, f"expected name-pattern fallback to flag template_id, got {result}"
        target_models = {fk.target_model for fk in template_records}
        assert DashboardTemplate in target_models
        assert all(fk.is_name_pattern for fk in template_records)

    def test_many_related_unscoped_is_flagged(self) -> None:
        result = discover_writable_tenant_fks(_ManyRelatedUnscopedSerializer)
        assert len(result) == 1
        fk = result[0]
        assert fk.serializer_field_name == "related_dashboards"
        assert fk.target_model is Dashboard
        assert fk.is_many is True
        assert fk.is_already_scoped is False

    def test_many_related_scoped_marked_already_scoped(self) -> None:
        result = discover_writable_tenant_fks(_ManyRelatedScopedSerializer)
        assert len(result) == 1
        assert result[0].is_many is True
        assert result[0].is_already_scoped is True

    def test_many_related_read_only_skipped(self) -> None:
        assert discover_writable_tenant_fks(_ManyRelatedReadOnlySerializer) == []

    def test_nested_many_related_one_level_deep(self) -> None:
        """A many=True PK field inside a nested ModelSerializer is still discovered."""
        result = discover_writable_tenant_fks(_ParentWithNestedManyRelatedSerializer)
        nested = [fk for fk in result if fk.nested_path]
        assert len(nested) == 1
        fk = nested[0]
        assert fk.serializer_field_name == "related_dashboards"
        assert fk.nested_path == ("destination",)
        assert fk.is_many is True
        assert fk.target_model is Dashboard


class _CopyTemplateBodySerializer(serializers.Serializer):
    source_template_id = serializers.UUIDField(required=True)


class _NoSchemaActionSerializer(serializers.Serializer):
    foo = serializers.CharField(required=True)


class _FakeViewSetWithAction(viewsets.ViewSet):
    @extend_schema(request=_CopyTemplateBodySerializer)
    @action(detail=False, methods=["post"], url_path="copy_between_projects")
    def copy_between_projects(self, request, **kwargs):
        return None  # body irrelevant for discovery

    @action(detail=True, methods=["get", "post"])
    def lookup_thing(self, request, pk=None):
        return None


class _FakeViewSetNoActions(viewsets.ViewSet):
    pass


class TestDiscoverActionSerializers:
    def test_finds_action_with_extend_schema_request(self) -> None:
        result = discover_action_serializers(_FakeViewSetWithAction)
        names = {c.method_name for c in result}
        assert "copy_between_projects" in names
        case = next(c for c in result if c.method_name == "copy_between_projects")
        assert case.serializer_cls is _CopyTemplateBodySerializer
        assert case.url_path == "copy_between_projects"
        assert case.http_methods == ("POST",)
        assert case.detail is False

    def test_skips_actions_without_extend_schema_request(self) -> None:
        result = discover_action_serializers(_FakeViewSetWithAction)
        # `lookup_thing` has no @extend_schema(request=...), so it isn't returned.
        names = {c.method_name for c in result}
        assert "lookup_thing" not in names

    def test_no_actions_returns_empty(self) -> None:
        assert discover_action_serializers(_FakeViewSetNoActions) == []

    def test_non_viewset_returns_empty(self) -> None:
        class _NotAViewSet:
            pass

        assert discover_action_serializers(_NotAViewSet) == []


class TestDiscoverFilterParams:
    def test_no_filterset_fields_returns_empty(self) -> None:
        class _NoFilters:
            pass

        assert discover_filter_params(_NoFilters) == []

    def test_non_tenant_param_skipped(self) -> None:
        class _ViewSet:
            filterset_fields = ["status", "archived", "is_staff"]

        assert discover_filter_params(_ViewSet) == []

    def test_param_matching_tenant_model_picked_up(self) -> None:
        class _ViewSet:
            filterset_fields = ["dashboard"]

        result = discover_filter_params(_ViewSet)
        assert len(result) == 1
        record = result[0]
        assert record.param_name == "dashboard"
        assert record.target_model is Dashboard

    def test_id_suffix_stripped(self) -> None:
        class _ViewSet:
            filterset_fields = ["cohort_id"]

        result = discover_filter_params(_ViewSet)
        assert len(result) == 1
        record = result[0]
        assert record.param_name == "cohort_id"
        assert record.target_model is Cohort

    def test_double_underscore_lookup_kept_as_param_name(self) -> None:
        # `?dashboard__id=<pk>` is the DRF lookup syntax for a foreign-key id.
        # The runtime test must hit the exact param shape, but the head
        # `dashboard` is what determines the target model.
        class _ViewSet:
            filterset_fields = ["dashboard__id"]

        result = discover_filter_params(_ViewSet)
        assert any(r.target_model is Dashboard and r.param_name == "dashboard__id" for r in result)

    def test_dict_form_filterset_fields(self) -> None:
        class _ViewSet:
            filterset_fields = {"cohort": ["exact", "in"]}

        result = discover_filter_params(_ViewSet)
        assert len(result) == 1
        assert result[0].target_model is Cohort

    def test_role_prefix_stripped(self) -> None:
        class _ViewSet:
            filterset_fields = ["source_dashboard"]

        result = discover_filter_params(_ViewSet)
        assert any(r.target_model is Dashboard for r in result)

    def test_search_fields_not_included(self) -> None:
        # search_fields drive `?search=<text>`, which is a different IDOR
        # shape (free-form search) and is intentionally out of scope.
        class _ViewSet:
            search_fields = ["dashboard__name"]

        assert discover_filter_params(_ViewSet) == []

    def test_filterparam_carries_scope(self) -> None:
        record = FilterParam(param_name="cohort", target_model=Cohort, scope="team")
        assert record.scope == "team"
        assert record.target_model is Cohort
