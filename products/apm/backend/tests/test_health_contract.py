from django.test import SimpleTestCase

from parameterized import parameterized

from products.apm.backend.logic.health.contract import HealthRow, HealthStatus, ServiceHealth, rank_services, status_of


def _row(
    request_rate: float | None = 10.0,
    error_rate: float | None = 0.0,
    p95_ms: float | None = 100.0,
    span_count: int = 600,
    error_count: int = 0,
) -> HealthRow:
    return HealthRow(
        request_rate=request_rate,
        error_rate=error_rate,
        p95_ms=p95_ms,
        span_count=span_count,
        error_count=error_count,
    )


class TestStatusOf(SimpleTestCase):
    @parameterized.expand(
        [
            ("zero_errors", 0.0, HealthStatus.GOOD),
            ("under_one_percent", 0.009, HealthStatus.GOOD),
            ("one_percent", 0.01, HealthStatus.WARNING),
            ("just_under_five", 0.049, HealthStatus.WARNING),
            ("five_percent", 0.05, HealthStatus.SERIOUS),
            ("most_fail", 0.6, HealthStatus.SERIOUS),
        ]
    )
    def test_error_rate_bands(self, _name: str, error_rate: float, expected: HealthStatus) -> None:
        self.assertEqual(status_of(_row(error_rate=error_rate)), expected)

    def test_no_traffic_is_good(self) -> None:
        self.assertEqual(status_of(_row(request_rate=0.0, error_rate=None, span_count=0)), HealthStatus.GOOD)


class TestRankServices(SimpleTestCase):
    def test_worst_status_first_then_error_rate_then_name(self) -> None:
        rows = [
            ServiceHealth(service_name="c", environment="prod", health=_row(error_rate=0.004)),
            ServiceHealth(service_name="a", environment="prod", health=_row(error_rate=0.001)),
            ServiceHealth(service_name="b", environment="prod", health=_row(error_rate=0.06)),
            ServiceHealth(service_name="d", environment="prod", health=_row(error_rate=0.02)),
        ]
        self.assertEqual([r.service_name for r in rank_services(rows)], ["b", "d", "c", "a"])

    def test_equal_rows_sort_by_name(self) -> None:
        rows = [
            ServiceHealth(service_name="web", environment="prod", health=_row()),
            ServiceHealth(service_name="api", environment="prod", health=_row()),
        ]
        self.assertEqual([r.service_name for r in rank_services(rows)], ["api", "web"])

    def test_status_is_attached_to_each_row(self) -> None:
        ranked = rank_services([ServiceHealth(service_name="q", environment="prod", health=_row(error_rate=0.06))])
        self.assertEqual(ranked[0].status, HealthStatus.SERIOUS)
