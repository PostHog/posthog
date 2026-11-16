from posthog.test.base import BaseTest

from parameterized import parameterized

from products.data_catalog.backend.logic.validation import validate_metric_definition
from products.data_catalog.evals.catalog_synthesizer import (
    ACCOUNT_ENGAGEMENT_METRIC,
    ACTIVATION_FUNNEL_METRIC,
    CHURN_RISK_INJECTED_METRIC,
    CHURN_RISK_METRIC,
    CHURN_RISK_MISSING_SOURCE_METRIC,
    MRR_METRIC,
    NOISE_METRICS,
    WAREHOUSE_SIGNUPS_METRIC,
    CatalogMetric,
)

_CATALOG: tuple[CatalogMetric, ...] = (
    *NOISE_METRICS,
    MRR_METRIC,
    ACCOUNT_ENGAGEMENT_METRIC,
    WAREHOUSE_SIGNUPS_METRIC,
    ACTIVATION_FUNNEL_METRIC,
    CHURN_RISK_METRIC,
    CHURN_RISK_MISSING_SOURCE_METRIC,
    CHURN_RISK_INJECTED_METRIC,
)


class TestEvalCatalog(BaseTest):
    @parameterized.expand([(metric.name, metric) for metric in _CATALOG])
    def test_every_catalog_definition_passes_metric_validation(self, _name: str, metric: CatalogMetric) -> None:
        validate_metric_definition(metric.definition, self.team, self.user)
