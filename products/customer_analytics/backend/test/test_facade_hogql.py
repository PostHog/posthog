# The facade owns the PostgresTable defs that core exposes for Customer analytics accounts,
# custom properties, relationships, and feature requests. Core's own system-table suite
# is skipped on this product's CI shard by the isolation contract-check, so this guard lives
# in-product: it fails here if a backing table is renamed or a model column is renamed/dropped
# without updating facade/hogql.py, catching the drift on the shard that actually runs for
# model changes.
from uuid import uuid4

from posthog.test.base import NonAtomicBaseTest

from django.test import SimpleTestCase
from django.utils import timezone

from parameterized import parameterized

from posthog.hogql.database.models import ExpressionField, LazyJoin, Table
from posthog.hogql.errors import QueryError
from posthog.hogql.query import execute_hogql_query

from posthog.models import OrganizationMembership, TaggedItem, User
from posthog.models.organization import AvailableFeature

from products.customer_analytics.backend.facade.hogql import (
    account_custom_property_values,
    account_custom_property_values_history,
    account_resource_notebooks,
    account_tagged_items,
    accounts,
    custom_property_definitions,
    feature_request_account_links,
    feature_request_evidence,
    feature_request_history,
    feature_request_product_area_links,
    feature_request_product_areas,
    feature_requests,
)
from products.customer_analytics.backend.models import (
    Account,
    CustomPropertyDefinition,
    CustomPropertyValue,
    FeatureRequest,
    FeatureRequestAccountLink,
    FeatureRequestEvidence,
    FeatureRequestHistory,
    FeatureRequestProductArea,
    FeatureRequestProductAreaLink,
)
from products.notebooks.backend.models import ResourceNotebook

from ee.models.rbac.access_control import AccessControl


class TestFacadeHogqlSystemTables(SimpleTestCase):
    @parameterized.expand(
        [
            ("accounts", accounts, Account),
            ("custom_property_definitions", custom_property_definitions, CustomPropertyDefinition),
            ("account_custom_property_values", account_custom_property_values, CustomPropertyValue),
            ("account_custom_property_values_history", account_custom_property_values_history, CustomPropertyValue),
            ("account_tagged_items", account_tagged_items, TaggedItem),
            ("account_resource_notebooks", account_resource_notebooks, ResourceNotebook),
            ("feature_requests", feature_requests, FeatureRequest),
            ("feature_request_product_areas", feature_request_product_areas, FeatureRequestProductArea),
            ("feature_request_account_links", feature_request_account_links, FeatureRequestAccountLink),
            ("feature_request_evidence", feature_request_evidence, FeatureRequestEvidence),
            ("feature_request_product_area_links", feature_request_product_area_links, FeatureRequestProductAreaLink),
            ("feature_request_history", feature_request_history, FeatureRequestHistory),
        ]
    )
    def test_federated_table_matches_model(self, _name, table, model):
        assert table.postgres_table_name == model._meta.db_table, (
            f"system.{table.name} federates PostgreSQL table {table.postgres_table_name!r}, but "
            f"{model.__name__} is stored in {model._meta.db_table!r}. Update the PostgresTable def "
            f"in facade/hogql.py to match the model."
        )
        model_columns = {field.column for field in model._meta.concrete_fields}
        exposed_columns = {
            field.name for field in table.fields.values() if not isinstance(field, (ExpressionField, LazyJoin, Table))
        }
        missing = exposed_columns - model_columns
        assert not missing, (
            f"system.{table.name} exposes {sorted(missing)}, which no longer exist as columns on "
            f"{model.__name__}. Update the PostgresTable def in facade/hogql.py to match the model."
        )


class TestFeatureRequestHogqlAccess(NonAtomicBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def test_account_access_filters_requests_links_and_evidence(self) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()
        viewer = User.objects.create_and_join(self.organization, "feature-request-hogql-viewer@example.com", "testtest")
        membership = OrganizationMembership.objects.get(user=viewer, organization=self.organization)
        visible_account = Account.objects.unscoped().create(team=self.team, name="Visible account")
        denied_account = Account.objects.unscoped().create(team=self.team, name="Denied account")
        visible_request = FeatureRequest.objects.unscoped().create(team=self.team, title="Partly visible request")
        visible_link = FeatureRequestAccountLink.objects.unscoped().create(
            team=self.team, feature_request=visible_request, account=visible_account
        )
        denied_link = FeatureRequestAccountLink.objects.unscoped().create(
            team=self.team, feature_request=visible_request, account=denied_account
        )
        visible_image_id = uuid4()
        FeatureRequestEvidence.objects.unscoped().create(
            team=self.team,
            account_link=visible_link,
            source="conversation",
            summary="Visible evidence",
            image_ids=[visible_image_id],
        )
        FeatureRequestEvidence.objects.unscoped().create(
            team=self.team, account_link=denied_link, source="conversation", summary="Denied evidence"
        )
        FeatureRequestHistory.objects.unscoped().create(
            team=self.team,
            feature_request=visible_request,
            changes=[
                {
                    "field": "evidence",
                    "before": None,
                    "after": {
                        "account": {"id": str(denied_account.id), "name": denied_account.name},
                        "summary": "Denied evidence",
                    },
                }
            ],
            changed_at=timezone.now(),
        )
        denied_request = FeatureRequest.objects.unscoped().create(team=self.team, title="Denied request")
        FeatureRequestAccountLink.objects.unscoped().create(
            team=self.team, feature_request=denied_request, account=denied_account
        )
        AccessControl.objects.create(
            team=self.team,
            resource="account",
            resource_id=str(denied_account.id),
            access_level="none",
            organization_member=membership,
        )

        requests = execute_hogql_query("SELECT id FROM system.feature_requests", team=self.team, user=viewer).results
        links = execute_hogql_query(
            "SELECT id FROM system.feature_request_account_links", team=self.team, user=viewer
        ).results
        evidence = execute_hogql_query(
            "SELECT summary, image_ids FROM system.feature_request_evidence", team=self.team, user=viewer
        ).results
        history = execute_hogql_query(
            "SELECT changed_fields FROM system.feature_request_history", team=self.team, user=viewer
        ).results

        assert {str(row[0]) for row in requests} == {str(visible_request.id)}
        assert {str(row[0]) for row in links} == {str(visible_link.id)}
        assert evidence == [("Visible evidence", [str(visible_image_id)])]
        assert history == [(["evidence"],)]
        with self.assertRaises(QueryError):
            execute_hogql_query("SELECT changes FROM system.feature_request_history", team=self.team, user=viewer)
