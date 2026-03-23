import uuid

import pytest
from unittest.mock import MagicMock, patch

from posthog.models import Organization, Team
from posthog.models.hog_function_template import HogFunctionTemplate
from posthog.temporal.data_imports.sources.common.base import WebhookCreationResult

from products.data_warehouse.backend.external_data_source.webhooks import (
    create_and_register_webhook,
    get_or_create_webhook_hog_function,
)
from products.data_warehouse.backend.models.external_data_schema import ExternalDataSchema
from products.data_warehouse.backend.models.external_data_source import ExternalDataSource

pytestmark = [
    pytest.mark.django_db,
]


def _create_org_and_team() -> tuple[Organization, Team]:
    org = Organization.objects.create(name="Test Org")
    team = Team.objects.create(organization=org, name="Test Team")
    return org, team


def _create_hog_function_template(
    template_id: str = "template-warehouse-source-test",
    name: str = "Test webhook source",
    extra_inputs_schema: list[dict] | None = None,
) -> HogFunctionTemplate:
    inputs_schema = [
        {"key": "schema_mapping", "type": "json"},
        {"key": "source_id", "type": "string"},
    ]
    if extra_inputs_schema:
        inputs_schema.extend(extra_inputs_schema)

    return HogFunctionTemplate.objects.create(
        template_id=template_id,
        name=name,
        code="// test code",
        inputs_schema=inputs_schema,
        type="warehouse_source_webhook",
        status="alpha",
        category=[],
    )


def _create_external_data_source(team: Team) -> ExternalDataSource:
    return ExternalDataSource.objects.create(
        team=team,
        source_id=str(uuid.uuid4()),
        connection_id=str(uuid.uuid4()),
        source_type="Stripe",
        status=ExternalDataSource.Status.COMPLETED,
        job_inputs={"stripe_secret_key": "sk_test_123"},
    )


def _create_schemas(team: Team, source: ExternalDataSource, names: list[str]) -> list[ExternalDataSchema]:
    return [
        ExternalDataSchema.objects.create(
            team=team,
            name=name,
            source=source,
            should_sync=True,
            sync_type=ExternalDataSchema.SyncType.INCREMENTAL,
        )
        for name in names
    ]


def _make_webhook_source(
    template_id: str = "template-warehouse-source-test",
    resource_map: dict[str, str] | None = None,
) -> MagicMock:
    source = MagicMock()

    template_dc = MagicMock()
    template_dc.id = template_id
    source.webhook_template = template_dc

    source.webhook_resource_map = resource_map or {
        "Customers": "customer",
        "Invoices": "invoice",
    }
    return source


class TestGetOrCreateWebhookHogFunction:
    def test_returns_error_when_no_webhook_template(self):
        _, team = _create_org_and_team()
        source = MagicMock()
        source.webhook_template = None

        result = get_or_create_webhook_hog_function(team, source, "source-123", [])

        assert result.hog_function is None
        assert result.error == "No webhook template available for this source"

    def test_returns_error_when_template_not_in_db(self):
        _, team = _create_org_and_team()
        source = _make_webhook_source(template_id="nonexistent-template")

        result = get_or_create_webhook_hog_function(team, source, "source-123", [])

        assert result.hog_function is None
        assert result.error is not None
        assert "template not found" in result.error.lower()

    def test_creates_hog_function_with_schema_mapping(self):
        _, team = _create_org_and_team()
        _create_hog_function_template()
        source = _make_webhook_source()
        ext_source = _create_external_data_source(team)
        schemas = _create_schemas(team, ext_source, ["Customers", "Invoices"])

        result = get_or_create_webhook_hog_function(team, source, "source-123", schemas)

        assert result.hog_function_created is True
        assert result.error is None
        assert result.hog_function is not None
        assert result.hog_function.inputs is not None

        mapping = result.hog_function.inputs["schema_mapping"]["value"]
        assert mapping["customer"] == str(schemas[0].id)
        assert mapping["invoice"] == str(schemas[1].id)
        assert result.hog_function.inputs["source_id"]["value"] == "source-123"

    def test_skips_schemas_not_in_resource_map(self):
        _, team = _create_org_and_team()
        _create_hog_function_template()
        source = _make_webhook_source(resource_map={"Customers": "customer"})
        ext_source = _create_external_data_source(team)
        schemas = _create_schemas(team, ext_source, ["Customers", "UnknownTable"])

        result = get_or_create_webhook_hog_function(team, source, "source-123", schemas)

        assert result.hog_function is not None
        assert result.hog_function.inputs is not None

        mapping = result.hog_function.inputs["schema_mapping"]["value"]
        assert "customer" in mapping
        assert len(mapping) == 1

    def test_includes_extra_inputs(self):
        _, team = _create_org_and_team()
        _create_hog_function_template(
            extra_inputs_schema=[{"key": "signing_secret", "type": "string"}],
        )
        source = _make_webhook_source()
        ext_source = _create_external_data_source(team)
        schemas = _create_schemas(team, ext_source, ["Customers"])

        result = get_or_create_webhook_hog_function(
            team, source, "source-123", schemas, extra_inputs={"signing_secret": "sec_123"}
        )

        assert result.hog_function is not None
        assert result.hog_function.inputs is not None
        assert result.hog_function.inputs["signing_secret"]["value"] == "sec_123"

    def test_updates_existing_hog_function(self):
        _, team = _create_org_and_team()
        _create_hog_function_template()
        source = _make_webhook_source()
        ext_source = _create_external_data_source(team)
        schemas = _create_schemas(team, ext_source, ["Customers"])

        first_result = get_or_create_webhook_hog_function(team, source, "source-123", schemas)
        assert first_result.hog_function_created is True
        assert first_result.hog_function is not None

        hog_id = first_result.hog_function.id

        second_result = get_or_create_webhook_hog_function(team, source, "source-123", schemas)
        assert second_result.hog_function_created is False
        assert second_result.hog_function is not None
        assert second_result.hog_function.id == hog_id

    def test_merges_schema_mapping_on_update(self):
        _, team = _create_org_and_team()
        _create_hog_function_template()
        source = _make_webhook_source()
        ext_source = _create_external_data_source(team)

        customers_schema = _create_schemas(team, ext_source, ["Customers"])
        get_or_create_webhook_hog_function(team, source, "source-123", customers_schema)

        invoices_schema = _create_schemas(team, ext_source, ["Invoices"])
        result = get_or_create_webhook_hog_function(team, source, "source-123", invoices_schema)

        assert result.hog_function is not None
        assert result.hog_function.inputs is not None

        result.hog_function.refresh_from_db()
        mapping = result.hog_function.inputs["schema_mapping"]["value"]
        assert "customer" in mapping
        assert "invoice" in mapping

    @pytest.mark.parametrize(
        "cloud_deployment,expected_host",
        [
            ("US", "https://webhooks.us.posthog.com"),
            ("us", "https://webhooks.us.posthog.com"),
            ("EU", "https://webhooks.eu.posthog.com"),
            ("DEV", "https://app.dev.posthog.dev"),
        ],
    )
    def test_webhook_url_uses_cloud_deployment(self, cloud_deployment: str, expected_host: str):
        _, team = _create_org_and_team()
        _create_hog_function_template()
        source = _make_webhook_source()
        ext_source = _create_external_data_source(team)
        schemas = _create_schemas(team, ext_source, ["Customers"])

        with patch("products.data_warehouse.backend.external_data_source.webhooks.settings") as mock_settings:
            mock_settings.CLOUD_DEPLOYMENT = cloud_deployment
            result = get_or_create_webhook_hog_function(team, source, "source-123", schemas)

        assert result.webhook_url.startswith(expected_host)
        assert result.hog_function is not None
        assert str(result.hog_function.id) in result.webhook_url

    def test_webhook_url_falls_back_to_site_url(self):
        _, team = _create_org_and_team()
        _create_hog_function_template()
        source = _make_webhook_source()
        ext_source = _create_external_data_source(team)
        schemas = _create_schemas(team, ext_source, ["Customers"])

        with patch("products.data_warehouse.backend.external_data_source.webhooks.settings") as mock_settings:
            mock_settings.CLOUD_DEPLOYMENT = None
            mock_settings.SITE_URL = "https://self-hosted.example.com"
            result = get_or_create_webhook_hog_function(team, source, "source-123", schemas)

        assert result.webhook_url.startswith("https://self-hosted.example.com")

    def test_hog_function_fields_match_template(self):
        _, team = _create_org_and_team()
        db_template = _create_hog_function_template(name="My Template")
        source = _make_webhook_source()
        ext_source = _create_external_data_source(team)
        schemas = _create_schemas(team, ext_source, ["Customers"])

        result = get_or_create_webhook_hog_function(team, source, "source-123", schemas)

        hog = result.hog_function
        assert hog is not None
        assert hog.name == db_template.name
        assert hog.hog == db_template.code
        assert hog.template_id == db_template.template_id
        assert hog.type == "warehouse_source_webhook"
        assert hog.enabled is True


class TestCreateAndRegisterWebhook:
    def test_success_without_extra_inputs(self):
        _, team = _create_org_and_team()
        _create_hog_function_template()
        webhook_source = _make_webhook_source()
        ext_source = _create_external_data_source(team)
        schemas = _create_schemas(team, ext_source, ["Customers"])

        hog_fn_result = get_or_create_webhook_hog_function(team, webhook_source, "source-123", schemas)
        webhook_source.create_webhook.return_value = WebhookCreationResult(success=True)

        config = MagicMock()
        result = create_and_register_webhook(webhook_source, config, hog_fn_result, team.id)

        assert result.success is True
        assert result.webhook_url == hog_fn_result.webhook_url
        assert result.error is None
        webhook_source.create_webhook.assert_called_once_with(config, hog_fn_result.webhook_url, team.id)

    def test_success_saves_extra_inputs_to_hog_function(self):
        _, team = _create_org_and_team()
        _create_hog_function_template(
            extra_inputs_schema=[{"key": "webhook_secret", "type": "string"}],
        )
        webhook_source = _make_webhook_source()
        ext_source = _create_external_data_source(team)
        schemas = _create_schemas(team, ext_source, ["Customers"])

        hog_fn_result = get_or_create_webhook_hog_function(team, webhook_source, "source-123", schemas)
        webhook_source.create_webhook.return_value = WebhookCreationResult(
            success=True,
            extra_inputs={"webhook_secret": "whsec_123"},
        )

        config = MagicMock()
        result = create_and_register_webhook(webhook_source, config, hog_fn_result, team.id)

        assert result.success is True
        assert hog_fn_result.hog_function is not None
        assert hog_fn_result.hog_function.inputs is not None

        hog_fn_result.hog_function.refresh_from_db()
        assert hog_fn_result.hog_function.inputs["webhook_secret"]["value"] == "whsec_123"

    def test_failure_does_not_save_extra_inputs(self):
        _, team = _create_org_and_team()
        _create_hog_function_template()
        webhook_source = _make_webhook_source()
        ext_source = _create_external_data_source(team)
        schemas = _create_schemas(team, ext_source, ["Customers"])

        hog_fn_result = get_or_create_webhook_hog_function(team, webhook_source, "source-123", schemas)

        webhook_source.create_webhook.return_value = WebhookCreationResult(
            success=False,
            error="API error",
            extra_inputs={"webhook_secret": "whsec_123"},
        )

        config = MagicMock()
        result = create_and_register_webhook(webhook_source, config, hog_fn_result, team.id)

        assert result.success is False
        assert result.error == "API error"
        assert hog_fn_result.hog_function is not None
        assert hog_fn_result.hog_function.inputs is not None

        hog_fn_result.hog_function.refresh_from_db()
        assert "webhook_secret" not in hog_fn_result.hog_function.inputs

    def test_returns_webhook_url_from_hog_fn_result(self):
        _, team = _create_org_and_team()
        _create_hog_function_template()
        webhook_source = _make_webhook_source()
        ext_source = _create_external_data_source(team)
        schemas = _create_schemas(team, ext_source, ["Customers"])

        hog_fn_result = get_or_create_webhook_hog_function(team, webhook_source, "source-123", schemas)
        webhook_source.create_webhook.return_value = WebhookCreationResult(success=True)

        config = MagicMock()
        result = create_and_register_webhook(webhook_source, config, hog_fn_result, team.id)

        assert result.webhook_url == hog_fn_result.webhook_url
