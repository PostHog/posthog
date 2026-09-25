import pytest

import dagster
from parameterized import parameterized

from posthog.dags.personhog_shadow_lane import require_shadow_dsn


class TestRequireShadowDsn:
    @parameterized.expand(
        [
            ("postgres://user:pass@persons-shadow.cluster-abc.us-east-1.rds.amazonaws.com:5432/posthog",),
            ("postgres://user@localhost:5432/persons_shadow_test",),
        ]
    )
    def test_accepts_shadow_targets(self, url: str) -> None:
        require_shadow_dsn(url)

    @parameterized.expand(
        [
            (
                "postgres://user:pass@posthog-cloud-persons-prod-us-east-1.cluster-abc.us-east-1.rds.amazonaws.com:5432/posthog",
            ),
            ("postgres://user@localhost:5432/posthog_persons",),
            ("postgres://user:shadow@localhost:5432/posthog_persons",),
        ]
    )
    def test_rejects_non_shadow_targets(self, url: str) -> None:
        with pytest.raises(dagster.Failure):
            require_shadow_dsn(url)
