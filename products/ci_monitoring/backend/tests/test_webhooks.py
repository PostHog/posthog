import json

import pytest
from unittest.mock import patch

from django.test import RequestFactory

from products.ci_monitoring.backend.models import CIRun
from products.ci_monitoring.backend.presentation.webhooks import github_workflow_run_webhook

from .conftest import WEBHOOK_SECRET, make_webhook_payload, sign_payload


@pytest.mark.django_db
class TestWorkflowRunWebhook:
    @pytest.fixture(autouse=True)
    def _mock_secret(self):
        with patch(
            "products.ci_monitoring.backend.presentation.webhooks.get_github_webhook_secret",
            return_value=WEBHOOK_SECRET,
        ):
            yield

    def _post(self, payload, *, signature=None, event_type="workflow_run"):
        body = json.dumps(payload).encode()
        if signature is None:
            signature = sign_payload(payload)
        factory = RequestFactory()
        request = factory.post(
            "/webhooks/github/ci",
            data=body,
            content_type="application/json",
            HTTP_X_HUB_SIGNATURE_256=signature,
            HTTP_X_GITHUB_EVENT=event_type,
        )
        return github_workflow_run_webhook(request)

    def test_valid_payload_creates_ci_run(self, repo, mocker):
        mocker.patch("products.ci_monitoring.backend.tasks.tasks.ingest_ci_run_artifacts.delay")
        payload = make_webhook_payload()

        response = self._post(payload)

        assert response.status_code == 200
        assert CIRun.objects.filter(repo=repo, github_run_id=99999).exists()

    def test_invalid_signature_returns_403(self, repo):
        payload = make_webhook_payload()

        response = self._post(payload, signature="sha256=bad")

        assert response.status_code == 403
        assert CIRun.objects.count() == 0

    def test_unknown_repo_returns_200(self):
        payload = make_webhook_payload(repo_external_id=99999)

        response = self._post(payload)

        assert response.status_code == 200
        assert CIRun.objects.count() == 0

    def test_non_completed_action_ignored(self, repo):
        payload = make_webhook_payload(action="requested")

        response = self._post(payload)

        assert response.status_code == 200
        assert CIRun.objects.count() == 0

    def test_non_workflow_run_event_ignored(self, repo):
        payload = make_webhook_payload()

        response = self._post(payload, event_type="push")

        assert response.status_code == 200
        assert CIRun.objects.count() == 0

    def test_dispatches_ingestion_task(self, repo, mocker):
        mock_delay = mocker.patch("products.ci_monitoring.backend.tasks.tasks.ingest_ci_run_artifacts.delay")
        payload = make_webhook_payload()

        self._post(payload)

        ci_run = CIRun.objects.get(repo=repo)
        mock_delay.assert_called_once_with(ci_run_id=str(ci_run.id))
