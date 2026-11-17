from posthog.test.base import APIBaseTest

from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature

from products.access_control.backend.models.property_access_control import PropertyAccessControl
from products.access_control.backend.models.role import Role, RoleMembership
from products.ai_observability.backend.models.clustering_config import ClusteringConfig
from products.ai_observability.backend.models.clustering_job import ClusteringJob
from products.event_definitions.backend.models import PropertyDefinition


class TestClusteringConfigViewSet(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.organization.is_ai_data_processing_approved = True
        self.organization.save(update_fields=["is_ai_data_processing_approved"])

    def test_enabling_preserves_legacy_filters_in_default_jobs(self):
        filters = [{"key": "$ai_model", "value": "example-model", "operator": "exact", "type": "event"}]
        ClusteringConfig.objects.create(team=self.team, event_filters=filters)
        response = self.client.post(
            f"/api/projects/{self.team.id}/llm_analytics/clustering_config/set_enabled/",
            {"enabled": True},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            list(ClusteringJob.objects.filter(team=self.team).values_list("event_filters", flat=True)), [filters] * 3
        )

    @parameterized.expand([(8,), (9,), (10,)])
    def test_enabling_adds_defaults_only_within_the_job_limit(self, count):
        for i in range(count):
            ClusteringJob.objects.create(team=self.team, name=f"Traces {i}", analysis_level="trace")
        response = self.client.post(
            f"/api/projects/{self.team.id}/llm_analytics/clustering_config/set_enabled/",
            {"enabled": True},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.data["enabled"])
        self.assertEqual(ClusteringJob.objects.filter(team=self.team).count(), 10)

    @parameterized.expand(
        [
            (subject, property_type, restricted_type, restricted_key, key, group_index)
            for subject in ("member", "role")
            for property_type, restricted_type, restricted_key, key, group_index in (
                ("event", PropertyDefinition.Type.EVENT, "private_property", "private_property", None),
                ("event", PropertyDefinition.Type.EVENT, "private_property", "", None),
                ("person", PropertyDefinition.Type.PERSON, "private_property", "", None),
                ("group", PropertyDefinition.Type.GROUP, "private_property", "", 0),
                ("event", PropertyDefinition.Type.EVENT, "$raw_user_agent", "$virt_bot_name", None),
                ("event", PropertyDefinition.Type.EVENT, "$ip", "$virt_bot_name", None),
                ("event", PropertyDefinition.Type.EVENT, "$feature/private-flag", "$active_feature_flags", None),
                ("event", PropertyDefinition.Type.EVENT, "$feature/private-flag", "$feature_flags", None),
                ("event", PropertyDefinition.Type.EVENT, "$feature_flags", "$active_feature_flags", None),
                ("event", PropertyDefinition.Type.EVENT, "$feature_flags", "$feature/private-flag", None),
                ("event", PropertyDefinition.Type.EVENT, "private_property", "private_property.nested", None),
                ("event", PropertyDefinition.Type.EVENT, "private_property.nested", "private_property", None),
                ("event", PropertyDefinition.Type.EVENT, "private_property.nested", "private_property%2Enested", None),
                (
                    "person",
                    PropertyDefinition.Type.PERSON,
                    "private_property.nested",
                    "private_property%2Enested",
                    None,
                ),
                ("event", PropertyDefinition.Type.PERSON, "private_property", "$set.private_property", None),
                ("group", PropertyDefinition.Type.GROUP, "private_property", "private_property", 0),
                ("group", PropertyDefinition.Type.GROUP, "private_property", "private_property", "0"),
            )
        ]
    )
    def test_restricted_filters_cannot_be_saved(
        self, subject, property_type, restricted_type, restricted_key, key, group_index
    ):
        reader = self._create_user("cluster-reader@example.com")
        self.organization.available_product_features = [
            {"name": feature, "key": feature}
            for feature in [AvailableFeature.PROPERTY_ACCESS_CONTROL, AvailableFeature.ROLE_BASED_ACCESS]
        ]
        self.organization.save()
        definition = PropertyDefinition.objects.create(
            team=self.team,
            name=restricted_key,
            type=restricted_type,
            group_type_index=0 if property_type == "group" else None,
        )
        member = reader.organization_memberships.get(organization=self.organization)
        role = Role.objects.create(name="Restricted", organization=self.organization)
        RoleMembership.objects.create(role=role, user=reader, organization_member=member)
        PropertyAccessControl.objects.create(
            team=self.team,
            property_definition=definition,
            organization_member=member if subject == "member" else None,
            role=role if subject == "role" else None,
            access_level="none",
        )
        filters = [
            {
                "key": key,
                "type": property_type,
                "operator": "exact",
                "value": "example",
                "group_type_index": group_index,
            }
        ]
        ClusteringConfig.objects.create(team=self.team, enabled=True)
        url = f"/api/projects/{self.team.id}/llm_analytics/clustering_jobs/"
        response = self.client.post(
            url, {"name": "Filtered", "analysis_level": "evaluation", "event_filters": filters}, format="json"
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.client.force_login(reader)
        response = self.client.post(
            url, {"name": "Reader job", "analysis_level": "evaluation", "event_filters": filters}, format="json"
        )
        self.assertEqual(response.status_code, 403, response.data)

    def test_enable_requires_ai_processing_consent(self):
        self.organization.is_ai_data_processing_approved = False
        self.organization.save(update_fields=["is_ai_data_processing_approved"])
        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/clustering_config/set_enabled/",
            {"enabled": True},
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_projects_are_off_until_explicitly_enabled(self):
        response = self.client.get(f"/api/environments/{self.team.id}/llm_analytics/clustering_config/")
        self.assertFalse(response.data["enabled"])
        self.assertFalse(ClusteringJob.objects.filter(team=self.team).exists())

        url = f"/api/environments/{self.team.id}/llm_analytics/clustering_config/set_enabled/"
        for _ in range(2):
            response = self.client.post(url, {"enabled": True}, format="json")
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertTrue(response.data["enabled"])
        self.assertCountEqual(
            ClusteringJob.objects.filter(team=self.team, enabled=True).values_list("analysis_level", flat=True),
            ["trace", "generation", "evaluation"],
        )

    def test_disable_and_reenable_preserve_custom_jobs_and_filters(self):
        filters = [{"key": "$ai_model", "value": "gpt-4", "operator": "exact", "type": "event"}]
        ClusteringConfig.objects.create(team=self.team, enabled=True, event_filters=filters)
        job = ClusteringJob.objects.create(
            team=self.team, name="Production traces", analysis_level="trace", event_filters=filters
        )
        url = f"/api/environments/{self.team.id}/llm_analytics/clustering_config/set_enabled/"
        response = self.client.post(url, {"enabled": False}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data["enabled"])
        self.assertEqual(response.data["event_filters"], filters)
        job.refresh_from_db()
        self.assertTrue(job.enabled)
        self.client.post(url, {"enabled": True}, format="json")
        self.assertEqual(ClusteringJob.objects.filter(team=self.team, analysis_level="trace").count(), 1)
        job.refresh_from_db()
        self.assertEqual(job.event_filters, filters)

    def test_set_enabled_requires_a_boolean(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/clustering_config/set_enabled/",
            {"enabled": "please"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(ClusteringConfig.objects.filter(team=self.team, enabled=True).exists())

    def test_unauthenticated_user_cannot_access_config(self):
        self.client.logout()
        response = self.client.get(f"/api/environments/{self.team.id}/llm_analytics/clustering_config/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_can_get_clustering_config(self):
        response = self.client.get(f"/api/environments/{self.team.id}/llm_analytics/clustering_config/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertIn("event_filters", response.data)
        self.assertIn("created_at", response.data)
        self.assertIn("updated_at", response.data)
        self.assertEqual(response.data["event_filters"], [])

    def test_get_creates_config_if_missing(self):
        self.assertEqual(ClusteringConfig.objects.filter(team=self.team).count(), 0)

        response = self.client.get(f"/api/environments/{self.team.id}/llm_analytics/clustering_config/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertEqual(ClusteringConfig.objects.filter(team=self.team).count(), 1)

    def test_get_returns_existing_config(self):
        ClusteringConfig.objects.create(
            team=self.team,
            event_filters=[{"key": "ai_product", "value": "posthog_ai", "operator": "exact", "type": "event"}],
        )

        response = self.client.get(f"/api/environments/{self.team.id}/llm_analytics/clustering_config/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["event_filters"]), 1)
        self.assertEqual(response.data["event_filters"][0]["key"], "ai_product")

    def test_can_set_event_filters(self):
        filters = [{"key": "$ai_model", "value": "gpt-4", "operator": "exact", "type": "event"}]

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/clustering_config/set_event_filters/",
            {"event_filters": filters},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["event_filters"], filters)

        config = ClusteringConfig.objects.get(team=self.team)
        self.assertEqual(config.event_filters, filters)

    def test_can_clear_event_filters(self):
        ClusteringConfig.objects.create(
            team=self.team,
            event_filters=[{"key": "ai_product", "value": "posthog_ai", "operator": "exact", "type": "event"}],
        )

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/clustering_config/set_event_filters/",
            {"event_filters": []},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["event_filters"], [])

    def test_set_event_filters_requires_event_filters_field(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/clustering_config/set_event_filters/",
            {},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("event_filters", response.data["detail"].lower())

    def test_set_event_filters_rejects_non_list(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/clustering_config/set_event_filters/",
            {"event_filters": "not a list"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("list", response.data["detail"].lower())

    def test_set_event_filters_persists_across_requests(self):
        filters = [
            {"key": "ai_product", "value": "posthog_ai", "operator": "exact", "type": "event"},
            {"key": "$ai_model", "value": "gpt-4", "operator": "exact", "type": "event"},
        ]

        self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/clustering_config/set_event_filters/",
            {"event_filters": filters},
            format="json",
        )

        response = self.client.get(f"/api/environments/{self.team.id}/llm_analytics/clustering_config/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["event_filters"]), 2)

    # The default test client uses force_login, which skips the scope check, so these
    # cases use a real Personal API Key — the path MCP and OAuth callers take — to lock
    # the scope the MCP tools must declare (ai_observability_clusters, not llm_analytics).
    @parameterized.expand(
        [
            ("correct_read_scope", ["ai_observability_clusters:read"], status.HTTP_200_OK),
            ("write_scope_grants_read", ["ai_observability_clusters:write"], status.HTTP_200_OK),
            ("wrong_scope_denied", ["llm_analytics:read"], status.HTTP_403_FORBIDDEN),
        ]
    )
    def test_get_config_pak_scope(self, _name: str, scopes: list[str], expected_status: int) -> None:
        api_key = self.create_personal_api_key_with_scopes(scopes)
        self.client.logout()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {api_key}")
        response = self.client.get(f"/api/environments/{self.team.id}/llm_analytics/clustering_config/")
        self.assertEqual(response.status_code, expected_status)

    # set_event_filters carries its own required_scopes override rather than inheriting
    # scope_object, so it needs separate coverage from the list action above.
    @parameterized.expand(
        [
            ("correct_write_scope", ["ai_observability_clusters:write"], status.HTTP_200_OK),
            ("read_scope_denied", ["ai_observability_clusters:read"], status.HTTP_403_FORBIDDEN),
            ("wrong_scope_denied", ["llm_analytics:write"], status.HTTP_403_FORBIDDEN),
        ]
    )
    def test_set_event_filters_pak_scope(self, _name: str, scopes: list[str], expected_status: int) -> None:
        api_key = self.create_personal_api_key_with_scopes(scopes)
        self.client.logout()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {api_key}")
        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/clustering_config/set_event_filters/",
            {"event_filters": []},
            format="json",
        )
        self.assertEqual(response.status_code, expected_status)
