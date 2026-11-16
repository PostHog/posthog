from unittest.mock import MagicMock, patch

from django.test import TestCase

from parameterized import parameterized

from posthog.models import Organization, Team

from products.ai_observability.backend.models.clustering_config import ClusteringConfig
from products.ai_observability.backend.models.clustering_job import ClusteringJob

from .eligibility import _skip_list_cache
from .execution import is_current_job
from .scope import scope_key


class TestClusteringExecution(TestCase):
    def setUp(self) -> None:
        super().setUp()
        _skip_list_cache.clear()
        self.addCleanup(_skip_list_cache.clear)
        self.organization = Organization.objects.create(name="Test", is_ai_data_processing_approved=True)
        self.team = Team.objects.create(organization=self.organization)
        self.config = ClusteringConfig.objects.create(team=self.team, enabled=True)
        self.job = ClusteringJob.objects.create(team=self.team, name="Traces", analysis_level="trace")
        self.scope = scope_key(self.job.analysis_level, self.job.event_filters)

    @parameterized.expand(
        [
            ("project_disabled", "config", {"enabled": False}),
            ("consent_revoked", "organization", {"is_ai_data_processing_approved": False}),
            ("job_disabled", "job", {"enabled": False}),
            ("job_changed", "job", {"event_filters": [{"key": "model", "value": "test-model", "type": "event"}]}),
        ]
    )
    @patch("posthoganalytics.get_feature_flag_payload", return_value={})
    def test_repeated_checks_cache_only_the_operational_flag(
        self, _name: str, changed_object: str, changes: dict, flag: MagicMock
    ) -> None:
        for _ in range(3):
            assert is_current_job(self.team.id, str(self.job.id), self.scope)

        instance = getattr(self, changed_object)
        for field, value in changes.items():
            setattr(instance, field, value)
        instance.save(update_fields=list(changes))

        assert not is_current_job(self.team.id, str(self.job.id), self.scope)
        flag.assert_called_once_with("llm-analytics-clustering-workflows", "internal_llma_team_discovery")

    @patch("posthoganalytics.get_feature_flag_payload")
    def test_operational_exclusions_refresh_after_cache_expiry(self, flag: MagicMock) -> None:
        flag.return_value = {}
        assert is_current_job(self.team.id, str(self.job.id), self.scope)

        flag.return_value = {"skip_team_ids": [self.team.id]}
        assert is_current_job(self.team.id, str(self.job.id), self.scope)
        _skip_list_cache.expire(_skip_list_cache.timer() + 31)

        assert not is_current_job(self.team.id, str(self.job.id), self.scope)
