from parameterized import parameterized
from rest_framework import serializers

from posthog.api.cohort import CohortSerializer
from posthog.api.organization_member import OrganizationMemberSerializer
from posthog.api.shared import SearchMatchTypeSerializerMixin

from products.alerts.backend.api.alert import AlertSerializer
from products.cdp.backend.api.hog_function import HogFunctionMinimalSerializer, HogFunctionSerializer
from products.dashboards.backend.api.dashboard import DashboardBasicSerializer
from products.product_analytics.backend.api.insight import InsightBasicSerializer, InsightSerializer
from products.product_tours.backend.api.product_tour import ProductTourSerializer
from products.surveys.backend.api.survey import SurveySerializer

# Each product that migrates its saved-list search onto apply_trigram_search appends its
# serializer(s) here, so the MRO-ordering contract is pinned for every consumer.
SEARCH_LIST_SERIALIZERS = [
    ("insight_basic", InsightBasicSerializer),
    ("insight", InsightSerializer),
    ("organization_member", OrganizationMemberSerializer),
    ("dashboard_basic", DashboardBasicSerializer),
    ("hog_function_minimal", HogFunctionMinimalSerializer),
    ("hog_function", HogFunctionSerializer),
    ("survey", SurveySerializer),
    ("product_tour", ProductTourSerializer),
    ("alert", AlertSerializer),
    ("cohort", CohortSerializer),
]


class _DummySerializer(SearchMatchTypeSerializerMixin, serializers.Serializer):
    name = serializers.CharField()


class _Exact:
    name = "x"
    _is_exact = 1


class _Similar:
    name = "x"
    _is_exact = 0


class _Unsearched:
    name = "x"


class TestSearchMatchTypeSerializerMixin:
    @parameterized.expand(SEARCH_LIST_SERIALIZERS)
    def test_mixin_runs_before_model_serializer_in_mro(self, _name, serializer_class):
        mro = serializer_class.__mro__
        assert SearchMatchTypeSerializerMixin in mro, (
            f"{serializer_class.__name__} must mix in the search-match-type field"
        )
        assert mro.index(SearchMatchTypeSerializerMixin) < mro.index(serializers.ModelSerializer), (
            f"{serializer_class.__name__} must place SearchMatchTypeSerializerMixin before ModelSerializer so its "
            "to_representation runs in the super() chain and the field is stripped on non-search responses"
        )

    @parameterized.expand(SEARCH_LIST_SERIALIZERS)
    def test_field_is_declared(self, _name, serializer_class):
        assert "search_match_type" in serializer_class().fields

    @parameterized.expand(
        [
            ("exact match", _Exact(), "exact"),
            ("similar match", _Similar(), "similar"),
        ]
    )
    def test_field_present_and_labelled_on_search_results(self, _name, instance, expected):
        data = _DummySerializer().to_representation(instance)
        assert data["search_match_type"] == expected

    def test_field_stripped_when_not_a_search_result(self):
        data = _DummySerializer().to_representation(_Unsearched())
        assert "search_match_type" not in data

    def test_mixin_has_no_docstring_so_it_does_not_leak_into_component_descriptions(self):
        # inspect.getdoc walks the MRO; a docstring here would become every mixed-in serializer's
        # public OpenAPI/MCP component description.
        assert SearchMatchTypeSerializerMixin.__doc__ is None
