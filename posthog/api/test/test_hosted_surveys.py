import uuid
from datetime import UTC, datetime, timedelta

from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, patch

from django.db import IntegrityError

from posthog.models import ProxyRecord, Survey

from products.surveys.backend.models import SurveyDomain


class TestCustomDomainSurveyPage(APIBaseTest):
    def _create_survey_domain(self, domain: str = "surveys.example.com", **kwargs) -> SurveyDomain:
        proxy_record = ProxyRecord.objects.create(
            organization=self.organization,
            domain=domain,
            target_cname="abc123.proxy.posthog.com",
            status=ProxyRecord.Status.VALID,
            created_by=self.user,
        )
        return SurveyDomain.objects.create(
            team=self.team,
            domain=domain,
            proxy_record=proxy_record,
            created_by=self.user,
            **kwargs,
        )

    def _create_external_survey(self, **kwargs) -> Survey:
        name = kwargs.pop("name", f"Test Survey {uuid.uuid4().hex[:8]}")
        defaults = {
            "team": self.team,
            "name": name,
            "type": Survey.SurveyType.EXTERNAL_SURVEY,
            "questions": [{"id": str(uuid.uuid4()), "type": "open", "question": "Test?"}],
            "start_date": datetime.now(UTC) - timedelta(days=1),
            "end_date": None,
            "archived": False,
        }
        defaults.update(kwargs)
        return Survey.objects.create(**defaults)

    def test_without_domain_param_works_as_before(self):
        survey = self._create_external_survey()
        response = self.client.get(f"/external_surveys/{survey.id}/")
        assert response.status_code == 200
        assert str(survey.id) in response.content.decode()

    def test_valid_domain_and_matching_survey(self):
        self._create_survey_domain()
        survey = self._create_external_survey()

        response = self.client.get(f"/external_surveys/{survey.id}/?domain=surveys.example.com")
        assert response.status_code == 200
        assert str(survey.id) in response.content.decode()

    def test_unknown_domain_returns_404(self):
        survey = self._create_external_survey()
        response = self.client.get(f"/external_surveys/{survey.id}/?domain=unknown.example.com")
        assert response.status_code == 404
        assert "Survey not available" in response.content.decode()

    def test_cross_team_survey_rejected(self):
        self._create_survey_domain()

        from posthog.models.organization import Organization
        from posthog.models.project import Project
        from posthog.models.team import Team

        other_org = Organization.objects.create(name="Other Org")
        other_project = Project.objects.create(id=Team.objects.increment_id_sequence(), organization=other_org)
        other_team = Team.objects.create(id=other_project.id, project=other_project, organization=other_org)
        other_survey = Survey.objects.create(
            team=other_team,
            name="Other Survey",
            type=Survey.SurveyType.EXTERNAL_SURVEY,
            questions=[{"id": str(uuid.uuid4()), "type": "open", "question": "Test?"}],
            start_date=datetime.now(UTC) - timedelta(days=1),
        )

        response = self.client.get(f"/external_surveys/{other_survey.id}/?domain=surveys.example.com")
        assert response.status_code == 404

    def test_domain_with_non_valid_proxy_record_rejected(self):
        proxy_record = ProxyRecord.objects.create(
            organization=self.organization,
            domain="pending.example.com",
            target_cname="abc.proxy.posthog.com",
            status=ProxyRecord.Status.WAITING,
            created_by=self.user,
        )
        SurveyDomain.objects.create(
            team=self.team,
            domain="pending.example.com",
            proxy_record=proxy_record,
            created_by=self.user,
        )
        survey = self._create_external_survey()

        response = self.client.get(f"/external_surveys/{survey.id}/?domain=pending.example.com")
        assert response.status_code == 404

    def test_archived_survey_returns_404(self):
        self._create_survey_domain()
        survey = self._create_external_survey(archived=True)

        response = self.client.get(f"/external_surveys/{survey.id}/?domain=surveys.example.com")
        assert response.status_code == 404

    def test_not_yet_started_survey_returns_404(self):
        self._create_survey_domain()
        survey = self._create_external_survey(start_date=datetime.now(UTC) + timedelta(days=1))

        response = self.client.get(f"/external_surveys/{survey.id}/?domain=surveys.example.com")
        assert response.status_code == 404

    def test_query_params_preserved(self):
        self._create_survey_domain()
        survey = self._create_external_survey()

        response = self.client.get(
            f"/external_surveys/{survey.id}/?domain=surveys.example.com&name=Jane&email=jane@example.com"
        )
        assert response.status_code == 200


class TestSurveyDomainModel(APIBaseTest):
    def test_domain_uniqueness(self):
        proxy_record = ProxyRecord.objects.create(
            organization=self.organization,
            domain="unique.example.com",
            target_cname="abc.proxy.posthog.com",
            status=ProxyRecord.Status.VALID,
        )
        SurveyDomain.objects.create(
            team=self.team,
            domain="unique.example.com",
            proxy_record=proxy_record,
        )

        with self.assertRaises(IntegrityError):
            SurveyDomain.objects.create(
                team=self.team,
                domain="unique.example.com",
            )

    def test_one_domain_per_team(self):
        SurveyDomain.objects.create(team=self.team, domain="first.example.com")

        with self.assertRaises(IntegrityError):
            SurveyDomain.objects.create(team=self.team, domain="second.example.com")


class TestSurveyDomainAPI(APIBaseTest):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.organization.available_product_features = [{"key": "white_labelling", "name": "white_labelling"}]
        cls.organization.save()

    @property
    def url(self) -> str:
        return f"/api/projects/{self.team.id}/survey_domain/"

    def test_get_returns_404_when_no_domain(self):
        response = self.client.get(self.url)
        assert response.status_code == 404

    @patch("products.surveys.backend.api.survey_domain.sync_connect")
    def test_create_survey_domain(self, mock_sync_connect):
        mock_sync_connect.return_value = AsyncMock()

        response = self.client.post(
            self.url,
            {"domain": "surveys.mybrand.com", "redirect_url": "https://mybrand.com"},
            content_type="application/json",
        )
        assert response.status_code == 201
        data = response.json()
        assert data["domain"] == "surveys.mybrand.com"
        assert data["redirect_url"] == "https://mybrand.com"
        assert data["status"] == "waiting"
        assert data["target_cname"] is not None

    @patch("products.surveys.backend.api.survey_domain.sync_connect")
    def test_create_requires_white_labelling(self, mock_sync_connect):
        self.organization.available_product_features = []
        self.organization.save()

        response = self.client.post(
            self.url,
            {"domain": "surveys.mybrand.com"},
            content_type="application/json",
        )
        assert response.status_code == 402

        self.organization.available_product_features = [{"key": "white_labelling", "name": "white_labelling"}]
        self.organization.save()

    @patch("products.surveys.backend.api.survey_domain.sync_connect")
    def test_cannot_create_duplicate_domain(self, mock_sync_connect):
        mock_sync_connect.return_value = AsyncMock()

        self.client.post(self.url, {"domain": "surveys.mybrand.com"}, content_type="application/json")

        response = self.client.post(self.url, {"domain": "surveys.mybrand.com"}, content_type="application/json")
        assert response.status_code == 400
        assert "already exists" in response.json()["detail"]

    @patch("products.surveys.backend.api.survey_domain.sync_connect")
    def test_get_returns_domain_after_creation(self, mock_sync_connect):
        mock_sync_connect.return_value = AsyncMock()

        self.client.post(self.url, {"domain": "surveys.mybrand.com"}, content_type="application/json")

        response = self.client.get(self.url)
        assert response.status_code == 200
        assert response.json()["domain"] == "surveys.mybrand.com"

    @patch("products.surveys.backend.api.survey_domain.sync_connect")
    def test_update_redirect_url(self, mock_sync_connect):
        mock_sync_connect.return_value = AsyncMock()

        self.client.post(self.url, {"domain": "surveys.mybrand.com"}, content_type="application/json")

        response = self.client.patch(
            f"{self.url}update/",
            {"redirect_url": "https://mybrand.com/new"},
            content_type="application/json",
        )
        assert response.status_code == 200
        assert response.json()["redirect_url"] == "https://mybrand.com/new"

    @patch("products.surveys.backend.api.survey_domain.sync_connect")
    def test_delete_domain_in_waiting_state(self, mock_sync_connect):
        mock_sync_connect.return_value = AsyncMock()

        self.client.post(self.url, {"domain": "surveys.mybrand.com"}, content_type="application/json")

        response = self.client.delete(f"{self.url}delete/")
        assert response.status_code == 200
        assert SurveyDomain.objects.count() == 0
        assert ProxyRecord.objects.filter(domain="surveys.mybrand.com").count() == 0

    @patch("products.surveys.backend.api.survey_domain.sync_connect")
    def test_delete_domain_in_valid_state_starts_workflow(self, mock_sync_connect):
        mock_sync_connect.return_value = AsyncMock()

        self.client.post(self.url, {"domain": "surveys.mybrand.com"}, content_type="application/json")

        proxy_record = ProxyRecord.objects.get(domain="surveys.mybrand.com")
        proxy_record.status = ProxyRecord.Status.VALID
        proxy_record.save()

        response = self.client.delete(f"{self.url}delete/")
        assert response.status_code == 200
        assert SurveyDomain.objects.count() == 0
        proxy_record.refresh_from_db()
        assert proxy_record.status == ProxyRecord.Status.DELETING

    def test_create_domain_empty_name(self):
        response = self.client.post(self.url, {"domain": ""}, content_type="application/json")
        assert response.status_code == 400

    @patch("products.surveys.backend.api.survey_domain.sync_connect")
    def test_domain_conflicts_with_existing_proxy_record(self, mock_sync_connect):
        ProxyRecord.objects.create(
            organization=self.organization,
            domain="existing-proxy.example.com",
            target_cname="abc.proxy.posthog.com",
        )

        response = self.client.post(
            self.url,
            {"domain": "existing-proxy.example.com"},
            content_type="application/json",
        )
        assert response.status_code == 400
        assert "reverse proxy" in response.json()["detail"]
