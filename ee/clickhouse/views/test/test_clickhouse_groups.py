import json
import base64
from typing import Any, cast
from uuid import UUID

import pytest
from freezegun.api import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, snapshot_clickhouse_queries
from unittest import mock
from unittest.mock import patch

from django.core.cache import cache
from django.db import IntegrityError
from django.utils.timezone import now

import orjson
from rest_framework import status

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.helpers.dashboard_templates import create_group_type_mapping_detail_dashboard
from posthog.models import GroupUsageMetric, PropertyDefinition
from posthog.models.filters.utils import GroupTypeIndex
from posthog.models.group.group import Group
from posthog.models.group.util import ListGroupsResult, create_group, list_groups, raw_create_group_ch
from posthog.models.group_type_mapping import (
    GROUP_TYPES_CACHE_KEY_PREFIX,
    GROUP_TYPES_STALE_CACHE_KEY_PREFIX,
    get_group_type_mapping_instance,
    get_group_types_for_project,
    update_group_type_mapping_fields,
)
from posthog.models.organization import Organization
from posthog.models.sharing_configuration import SharingConfiguration
from posthog.models.team.team import Team
from posthog.test.persons import create_group_type_mapping, create_person
from posthog.test.test_utils import create_group_type_mapping_without_created_at

from products.notebooks.backend.models import Notebook, ResourceNotebook

from ee.clickhouse.views.groups import _decode_groups_cursor, _encode_groups_cursor

PATH = "ee.clickhouse.views.groups"


def typed_group_type_index(value: int) -> GroupTypeIndex:
    return cast(GroupTypeIndex, value)


class GroupsViewSetTestCase(ClickhouseTestMixin, APIBaseTest):
    maxDiff = None

    @freeze_time("2021-05-02")
    def test_groups_list(self):
        with freeze_time("2021-05-01"):
            create_group(
                team_id=self.team.pk,
                group_type_index=0,
                group_key="org:5",
                properties={"industry": "finance", "name": "Mr. Krabs"},
            )
        with freeze_time("2021-05-02"):
            create_group(
                team_id=self.team.pk,
                group_type_index=0,
                group_key="org:6",
                properties={"industry": "technology"},
            )
        create_group(
            team_id=self.team.pk,
            group_type_index=1,
            group_key="company:1",
            properties={"name": "Plankton"},
        )

        response_data = self.client.get(f"/api/projects/{self.team.id}/groups?group_type_index=0").json()
        self.assertEqual(
            response_data,
            {
                "next": None,
                "previous": None,
                "results": [
                    {
                        "created_at": "2021-05-02T00:00:00Z",
                        "group_key": "org:6",
                        "group_properties": {"industry": "technology"},
                        "group_type_index": 0,
                    },
                    {
                        "created_at": "2021-05-01T00:00:00Z",
                        "group_key": "org:5",
                        "group_properties": {
                            "industry": "finance",
                            "name": "Mr. Krabs",
                        },
                        "group_type_index": 0,
                    },
                ],
            },
        )
        response_data = self.client.get(f"/api/projects/{self.team.id}/groups?group_type_index=0&search=Krabs").json()
        self.assertEqual(
            response_data,
            {
                "next": None,
                "previous": None,
                "results": [
                    {
                        "created_at": "2021-05-01T00:00:00Z",
                        "group_key": "org:5",
                        "group_properties": {
                            "industry": "finance",
                            "name": "Mr. Krabs",
                        },
                        "group_type_index": 0,
                    },
                ],
            },
        )

        response_data = self.client.get(f"/api/projects/{self.team.id}/groups?group_type_index=0&search=org:5").json()
        self.assertEqual(
            response_data,
            {
                "next": None,
                "previous": None,
                "results": [
                    {
                        "created_at": "2021-05-01T00:00:00Z",
                        "group_key": "org:5",
                        "group_properties": {
                            "industry": "finance",
                            "name": "Mr. Krabs",
                        },
                        "group_type_index": 0,
                    },
                ],
            },
        )

    @freeze_time("2021-05-02")
    def test_groups_list_no_group_type(self):
        response_data = self.client.get(f"/api/projects/{self.team.id}/groups/").json()
        self.assertEqual(
            response_data,
            {
                "type": "validation_error",
                "attr": "group_type_index",
                "code": "invalid_input",
                "detail": mock.ANY,
            },
        )

    def test_retrieve_group_wrong_group_type_index(self):
        group = create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key="key",
            properties={"industry": "finance", "name": "Mr. Krabs"},
        )

        response = self.client.get(
            f"/api/projects/{self.team.id}/groups/find?group_type_index=1&group_key={group.group_key}"
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND, "Should return 404 Not Found")

    def test_retrieve_group_wrong_group_key(self):
        group = create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key="key",
            properties={"industry": "finance", "name": "Mr. Krabs"},
        )

        response = self.client.get(
            f"/api/projects/{self.team.id}/groups/find?group_type_index={group.group_type_index}&group_key=wrong_key"
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND, "Should return 404 Not Found")

    def test_find_missing_group_key(self):
        response = self.client.get(f"/api/projects/{self.team.id}/groups/find?group_type_index=0")
        self.assertEqual(response.status_code, 400)

    @freeze_time("2021-05-02")
    @patch(f"{PATH}.feature_enabled_or_false", return_value=False)
    def test_retrieve_group_crm_disabled(self, _):
        index: GroupTypeIndex = 0
        key = "key"
        group = create_group(
            team_id=self.team.pk,
            group_type_index=index,
            group_key=key,
            properties={"industry": "finance", "name": "Mr. Krabs"},
        )

        response = self.client.get(f"/api/projects/{self.team.id}/groups/find?group_type_index={index}&group_key={key}")

        self.assertEqual(response.status_code, status.HTTP_200_OK, "Should return 200 OK")
        self.assertEqual(
            response.json(),
            {
                "created_at": "2021-05-02T00:00:00Z",
                "group_key": key,
                "group_properties": {"industry": "finance", "name": "Mr. Krabs"},
                "group_type_index": index,
                "notebook": None,
            },
        )
        self.assertFalse(ResourceNotebook.objects.filter(group=group.id).exists())
        self.assertEqual(0, Notebook.objects.filter(team=self.team).count())

    @freeze_time("2021-05-02")
    @patch(f"{PATH}.feature_enabled_or_false", return_value=True)
    def test_retrieve_group_crm_enabled(self, _):
        index: GroupTypeIndex = 0
        key = "key"
        group = create_group(
            team_id=self.team.pk,
            group_type_index=index,
            group_key=key,
            properties={"industry": "finance", "name": "Mr. Krabs"},
        )

        response = self.client.get(f"/api/projects/{self.team.id}/groups/find?group_type_index={index}&group_key={key}")

        self.assertEqual(response.status_code, status.HTTP_200_OK, "Should return 200 OK")
        relationships = ResourceNotebook.objects.filter(group=group.id)
        self.assertIsNotNone(relationships)
        relationship = relationships.first()
        assert relationship is not None
        self.assertEqual(
            response.json(),
            {
                "created_at": "2021-05-02T00:00:00Z",
                "group_key": key,
                "group_properties": {"industry": "finance", "name": "Mr. Krabs"},
                "group_type_index": index,
                "notebook": relationship.notebook.short_id,
            },
        )
        self.assertEqual(1, Notebook.objects.filter(team=self.team).count())

        # Test default notebook content structure
        notebook = relationship.notebook
        self.assertIsNotNone(notebook.content)
        self.assertEqual(notebook.content[0]["type"], "heading")
        self.assertEqual(notebook.content[0]["attrs"]["level"], 1)
        self.assertEqual(notebook.content[0]["content"][0]["text"], "Mr. Krabs Notes")
        self.assertEqual(notebook.content[1]["type"], "text")

    @freeze_time("2021-05-02")
    @patch(f"{PATH}.feature_enabled_or_false", return_value=True)
    def test_find_with_skip_create_notebook_does_not_create_notebook(self, _):
        index: GroupTypeIndex = 0
        key = "key"
        group = create_group(
            team_id=self.team.pk,
            group_type_index=index,
            group_key=key,
            properties={"industry": "finance", "name": "Mr. Krabs"},
        )

        response = self.client.get(
            f"/api/projects/{self.team.id}/groups/find?group_type_index={index}&group_key={key}&skip_create_notebook=true"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, "Should return 200 OK")
        self.assertEqual(response.json()["notebook"], None)
        self.assertFalse(ResourceNotebook.objects.filter(group=group.id).exists())
        self.assertEqual(0, Notebook.objects.filter(team=self.team).count())

    @freeze_time("2021-05-02")
    def test_retrieve_group_with_notebook(self):
        index: GroupTypeIndex = 0
        key = "key"
        group = create_group(
            team_id=self.team.pk,
            group_type_index=index,
            group_key=key,
            properties={"industry": "finance", "name": "Mr. Krabs"},
        )
        notebook = Notebook.objects.create(team=self.team, title="Mr. Krabs Notes")
        ResourceNotebook.objects.create(group=group.id, notebook=notebook)

        response = self.client.get(f"/api/projects/{self.team.id}/groups/find?group_type_index={index}&group_key={key}")

        self.assertEqual(response.status_code, status.HTTP_200_OK, "Should return 200 OK")
        self.assertEqual(
            response.json(),
            {
                "created_at": "2021-05-02T00:00:00Z",
                "group_key": key,
                "group_properties": {"industry": "finance", "name": "Mr. Krabs"},
                "group_type_index": index,
                "notebook": notebook.short_id,
            },
        )

    @freeze_time("2021-05-02")
    @patch("products.notebooks.backend.logic.ResourceNotebook.objects.create", side_effect=IntegrityError)
    @patch(f"{PATH}.feature_enabled_or_false", return_value=True)
    def test_retrieve_group_notebook_transaction_rollback(self, _, mock_relationship_create):
        index: GroupTypeIndex = 0
        key = "key"
        group = create_group(
            team_id=self.team.pk,
            group_type_index=index,
            group_key=key,
            properties={"industry": "finance", "name": "Mr. Krabs"},
        )

        initial_notebook_count = Notebook.objects.filter(team=self.team).count()
        self.assertEqual(initial_notebook_count, 0)

        with self.assertLogs(level="ERROR") as logs:
            response = self.client.get(
                f"/api/projects/{self.team.id}/groups/find?group_type_index={index}&group_key={key}"
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK, "Should return 200 OK")
        final_notebook_count = Notebook.objects.filter(team=self.team).count()
        self.assertEqual(final_notebook_count, initial_notebook_count, "Notebook creation should be rolled back")
        self.assertFalse(ResourceNotebook.objects.filter(group=group.id).exists())
        mock_relationship_create.assert_called_once()
        self.assertEqual(len(logs.records), 1)
        log = logs.records[0]
        message = cast(dict[str, Any], log.msg)
        self.assertEqual(message["group_key"], key)
        self.assertEqual(message["group_type_index"], index)
        self.assertEqual(message["team_id"], self.team.pk)
        self.assertEqual(message["event"], "Group notebook creation failed")

    @freeze_time("2021-05-02")
    @mock.patch("ee.clickhouse.views.groups.capture_internal")
    def test_create_group_missing_group_properties(self, mock_capture):
        group_type_mapping = create_group_type_mapping_without_created_at(
            team=self.team,
            project_id=self.team.project_id,
            group_type_index=0,
            group_type="organization",
        )
        group_key = "1234"

        response = self.client.post(
            f"/api/projects/{self.team.id}/groups",
            {
                "group_key": group_key,
                "group_type_index": group_type_mapping.group_type_index,
                "group_properties": None,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(
            response.json(),
            {
                "created_at": "2021-05-02T00:00:00Z",
                "group_key": group_key,
                "group_properties": {},
                "group_type_index": group_type_mapping.group_type_index,
            },
        )
        mock_capture.assert_called_once()

    @freeze_time("2021-05-02")
    @mock.patch("ee.clickhouse.views.groups.capture_internal")
    @pytest.mark.flaky(reruns=2)
    def test_create_group(self, mock_capture):
        group_type_mapping = create_group_type_mapping_without_created_at(
            team=self.team,
            project_id=self.team.project_id,
            group_type_index=0,
            group_type="organization",
        )
        group_properties = {"name": "Group Name", "industry": "finance"}
        group_key = "1234"

        response = self.client.post(
            f"/api/projects/{self.team.id}/groups",
            {
                "group_key": group_key,
                "group_type_index": group_type_mapping.group_type_index,
                "group_properties": group_properties,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(
            response.json(),
            {
                "created_at": "2021-05-02T00:00:00Z",
                "group_key": group_key,
                "group_properties": group_properties,
                "group_type_index": 0,
            },
        )
        hogql_response = execute_hogql_query(
            parse_select(
                """
                select properties
                from groups
                where index = {index}
                  and key = {key}
                """,
                placeholders={
                    "index": ast.Constant(value=group_type_mapping.group_type_index),
                    "key": ast.Constant(value=group_key),
                },
            ),
            self.team,
        )
        self.assertEqual(hogql_response.results, [(json.dumps(group_properties),)])
        mock_capture.assert_called_once_with(
            token=self.team.api_token,
            event_name="$groupidentify",
            event_source="ee_ch_views_groups",
            distinct_id=str(self.team.uuid),
            timestamp=mock.ANY,
            properties={
                "$group_type": group_type_mapping.group_type,
                "$group_key": group_key,
                "$group_set": group_properties,
            },
            process_person_profile=False,
        )

        response = self.client.get(
            f"/api/projects/{self.team.id}/groups/activity?group_key={group_key}&group_type_index=0",
        )

        self.assertEqual(response.status_code, 200)
        property_definitions = PropertyDefinition.objects.filter(
            team=self.team, type=PropertyDefinition.Type.GROUP, group_type_index=0
        )
        self.assertEqual(len(property_definitions), 2)
        name_prop = property_definitions.get(name="name")
        self.assertEqual(name_prop.property_type, "String")
        self.assertFalse(name_prop.is_numerical)

        industry_prop = property_definitions.get(name="industry")
        self.assertEqual(industry_prop.property_type, "String")
        self.assertFalse(industry_prop.is_numerical)

        results = response.json()["results"]
        self.assertEqual(len(results), 2)
        for result in results:
            self.assertEqual(result["activity"], "create_group")
            self.assertEqual(result["scope"], "Group")
            self.assertEqual(result["detail"]["changes"][0]["action"], "created")
            self.assertIsNone(result["detail"]["changes"][0]["before"])
            prop_name = result["detail"]["name"]
            self.assertEqual(result["detail"]["changes"][0]["after"], group_properties[prop_name])

    @mock.patch("ee.clickhouse.views.groups.capture_internal")
    def test_create_group_duplicated_group_key(self, mock_capture):
        group_type_mapping = create_group_type_mapping_without_created_at(
            team=self.team,
            project_id=self.team.project_id,
            group_type_index=0,
            group_type="organization",
        )
        group_key = "1234"
        create_group(
            team_id=self.team.pk,
            group_type_index=typed_group_type_index(group_type_mapping.group_type_index),
            group_key=group_key,
            properties={},
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/groups",
            {
                "group_key": group_key,
                "group_type_index": 0,
                "group_properties": {},
            },
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {
                "type": "validation_error",
                "code": "invalid_input",
                "detail": "A group with this key already exists",
                "attr": "detail",
            },
        )
        mock_capture.assert_not_called()

    @mock.patch("ee.clickhouse.views.groups.capture_internal")
    def test_create_group_duplicated_group_key_via_personhog(self, mock_capture):
        """Personhog upserts on duplicate so the pre-check must catch it."""
        from posthog.personhog_client.fake_client import fake_personhog_client

        group_type_mapping = create_group_type_mapping_without_created_at(
            team=self.team,
            project_id=self.team.project_id,
            group_type_index=0,
            group_type="organization",
        )
        group_key = "dup-key-ph"

        with fake_personhog_client() as fake:
            fake.add_group(
                team_id=self.team.pk,
                group_type_index=group_type_mapping.group_type_index,
                group_key=group_key,
                id=1,
            )

            response = self.client.post(
                f"/api/projects/{self.team.id}/groups",
                {
                    "group_key": group_key,
                    "group_type_index": 0,
                    "group_properties": {},
                },
            )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["detail"], "A group with this key already exists")
        create_calls = [c for c in fake.calls if c.method == "create_group"]
        self.assertEqual(len(create_calls), 0, "create_group should not be called for duplicates")
        mock_capture.assert_not_called()

    @mock.patch("ee.clickhouse.views.groups.capture_internal")
    def test_create_group_missing_group_key(self, mock_capture):
        group_type_mapping = create_group_type_mapping_without_created_at(
            team=self.team,
            project_id=self.team.project_id,
            group_type_index=0,
            group_type="organization",
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/groups",
            {
                "group_key": None,
                "group_type_index": group_type_mapping.group_type_index,
                "group_properties": {},
            },
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {
                "attr": "group_key",
                "code": "null",
                "detail": "This field may not be null.",
                "type": "validation_error",
            },
        )
        mock_capture.assert_not_called()

    @mock.patch("ee.clickhouse.views.groups.capture_internal")
    def test_create_group_missing_group_type_index(self, mock_capture):
        response = self.client.post(
            f"/api/projects/{self.team.id}/groups",
            {
                "group_key": "foo",
                "group_type_index": None,
                "group_properties": {},
            },
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {
                "attr": "group_type_index",
                "code": "null",
                "detail": "This field may not be null.",
                "type": "validation_error",
            },
        )
        mock_capture.assert_not_called()

    @freeze_time("2021-05-02")
    @mock.patch("ee.clickhouse.views.groups.capture_internal")
    @pytest.mark.flaky(reruns=2)
    def test_group_property_crud_add_success(self, mock_capture):
        group_type_mapping = create_group_type_mapping_without_created_at(
            team=self.team,
            project_id=self.team.project_id,
            group_type_index=0,
            group_type="organization",
        )
        group = create_group(
            team_id=self.team.pk,
            group_type_index=typed_group_type_index(group_type_mapping.group_type_index),
            group_key="org:5",
            properties={"name": "Mr. Krabs"},
        )
        create_group(
            team_id=self.team.pk,
            group_type_index=typed_group_type_index(group_type_mapping.group_type_index),
            group_key="org:55",
            properties={"name": "Mr. Krabs"},
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/groups/update_property?group_key=org:5&group_type_index=0",
            {"key": "industry", "value": "technology"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "created_at": "2021-05-02T00:00:00Z",
                "group_key": "org:5",
                "group_properties": {"industry": "technology", "name": "Mr. Krabs"},
                "group_type_index": 0,
            },
        )

        hogql_response = execute_hogql_query(
            parse_select(
                """
                select properties
                from groups
                where index = {index}
                  and key = {key}
                """,
                placeholders={
                    "index": ast.Constant(value=group.group_type_index),
                    "key": ast.Constant(value=group.group_key),
                },
            ),
            self.team,
        )
        self.assertEqual(hogql_response.results, [('{"name": "Mr. Krabs", "industry": "technology"}',)])

        mock_capture.assert_called_once_with(
            token=self.team.api_token,
            event_name="$groupidentify",
            event_source="ee_ch_views_groups",
            distinct_id=str(self.team.uuid),
            timestamp=mock.ANY,
            properties={
                "$group_type": group_type_mapping.group_type,
                "$group_key": group.group_key,
                "$group_set": {"industry": "technology"},
            },
            process_person_profile=False,
        )

        response = self.client.get(
            f"/api/projects/{self.team.id}/groups/activity?group_key=org:5&group_type_index=0",
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("results", response.json())
        self.assertEqual(len(response.json()["results"]), 1)
        self.assertEqual(response.json()["results"][0]["activity"], "create_property")
        self.assertEqual(response.json()["results"][0]["scope"], "Group")
        self.assertEqual(response.json()["results"][0]["item_id"], str(group.pk))
        self.assertEqual(response.json()["results"][0]["detail"]["changes"][0]["type"], "Group")
        self.assertEqual(response.json()["results"][0]["detail"]["changes"][0]["action"], "created")
        self.assertEqual(response.json()["results"][0]["detail"]["changes"][0]["before"], None)
        self.assertEqual(response.json()["results"][0]["detail"]["changes"][0]["after"], "technology")

    @freeze_time("2021-05-02")
    @mock.patch("ee.clickhouse.views.groups.capture_internal")
    @pytest.mark.flaky(reruns=2)
    def test_group_property_crud_update_success(self, mock_capture):
        group_type_mapping = create_group_type_mapping_without_created_at(
            team=self.team,
            project_id=self.team.project_id,
            group_type_index=0,
            group_type="organization",
        )
        group = create_group(
            team_id=self.team.pk,
            group_type_index=typed_group_type_index(group_type_mapping.group_type_index),
            group_key="org:5",
            properties={"industry": "finance", "name": "Mr. Krabs"},
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/groups/update_property?group_key=org:5&group_type_index=0",
            {"key": "industry", "value": "technology"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "created_at": "2021-05-02T00:00:00Z",
                "group_key": "org:5",
                "group_properties": {"industry": "technology", "name": "Mr. Krabs"},
                "group_type_index": 0,
            },
        )

        hogql_response = execute_hogql_query(
            parse_select(
                """
                select properties
                from groups
                where index = {index}
                  and key = {key}
                """,
                placeholders={
                    "index": ast.Constant(value=group.group_type_index),
                    "key": ast.Constant(value=group.group_key),
                },
            ),
            self.team,
        )
        # Check properties regardless of JSON key order
        self.assertEqual(len(hogql_response.results), 1)
        self.assertEqual(len(hogql_response.results[0]), 1)
        self.assertEqual(orjson.loads(hogql_response.results[0][0]), {"name": "Mr. Krabs", "industry": "technology"})

        mock_capture.assert_called_once_with(
            token=self.team.api_token,
            event_name="$groupidentify",
            event_source="ee_ch_views_groups",
            distinct_id=str(self.team.uuid),
            timestamp=mock.ANY,
            properties={
                "$group_type": group_type_mapping.group_type,
                "$group_key": group.group_key,
                "$group_set": {"industry": "technology"},
            },
            process_person_profile=False,
        )

        response = self.client.get(
            f"/api/projects/{self.team.id}/groups/activity?group_key=org:5&group_type_index=0",
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("results", response.json())
        self.assertEqual(len(response.json()["results"]), 1)
        self.assertEqual(response.json()["results"][0]["activity"], "update_property")
        self.assertEqual(response.json()["results"][0]["scope"], "Group")
        self.assertEqual(response.json()["results"][0]["item_id"], str(group.pk))
        self.assertEqual(response.json()["results"][0]["detail"]["changes"][0]["type"], "Group")
        self.assertEqual(response.json()["results"][0]["detail"]["changes"][0]["action"], "changed")
        self.assertEqual(response.json()["results"][0]["detail"]["changes"][0]["before"], "finance")
        self.assertEqual(response.json()["results"][0]["detail"]["changes"][0]["after"], "technology")

    @freeze_time("2021-05-02")
    def test_group_property_crud_update_missing_key(self):
        group_type_mapping = create_group_type_mapping_without_created_at(
            team=self.team,
            project_id=self.team.project_id,
            group_type_index=0,
            group_type="organization",
        )
        create_group(
            team_id=self.team.pk,
            group_type_index=typed_group_type_index(group_type_mapping.group_type_index),
            group_key="org:5",
            properties={"industry": "finance", "name": "Mr. Krabs"},
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/groups/update_property?group_key=org:5&group_type_index=0",
            {"value": "technology"},
        )
        self.assertEqual(response.status_code, 400)

    @freeze_time("2021-05-02")
    def test_group_property_crud_update_invalid_group_key(self):
        group_type_mapping = create_group_type_mapping_without_created_at(
            team=self.team,
            project_id=self.team.project_id,
            group_type_index=0,
            group_type="organization",
        )
        create_group(
            team_id=self.team.pk,
            group_type_index=typed_group_type_index(group_type_mapping.group_type_index),
            group_key="org:5",
            properties={"industry": "finance", "name": "Mr. Krabs"},
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/groups/update_property?group_key=org:0&group_type_index=0",
            {"key": "industry", "value": "technology"},
        )
        self.assertEqual(response.status_code, 404)

    @freeze_time("2021-05-02")
    @mock.patch("ee.clickhouse.views.groups.capture_internal")
    @pytest.mark.flaky(reruns=2)
    def test_group_property_crud_delete_success(self, mock_capture):
        group_type_mapping = create_group_type_mapping_without_created_at(
            team=self.team,
            project_id=self.team.project_id,
            group_type_index=0,
            group_type="organization",
        )
        group = create_group(
            team_id=self.team.pk,
            group_type_index=typed_group_type_index(group_type_mapping.group_type_index),
            group_key="org:5",
            properties={"industry": "finance", "name": "Mr. Krabs"},
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/groups/delete_property?group_key=org:5&group_type_index=0",
            {"$unset": "industry"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "created_at": "2021-05-02T00:00:00Z",
                "group_key": "org:5",
                "group_properties": {"name": "Mr. Krabs"},
                "group_type_index": 0,
            },
        )

        hogql_response = execute_hogql_query(
            parse_select(
                """
                select properties
                from groups
                where index = {index}
                  and key = {key}
                """,
                placeholders={
                    "index": ast.Constant(value=group.group_type_index),
                    "key": ast.Constant(value=group.group_key),
                },
            ),
            self.team,
        )
        self.assertEqual(hogql_response.results, [('{"name": "Mr. Krabs"}',)])

        mock_capture.assert_called_once_with(
            token=self.team.api_token,
            event_name="$delete_group_property",
            event_source="ee_ch_views_groups",
            distinct_id=str(self.team.uuid),
            timestamp=mock.ANY,
            properties={
                "$group_type": group_type_mapping.group_type,
                "$group_key": group.group_key,
                "$group_unset": ["industry"],
            },
            process_person_profile=False,
        )

        response = self.client.get(
            f"/api/projects/{self.team.id}/groups/activity?group_key=org:5&group_type_index=0",
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("results", response.json())
        self.assertEqual(len(response.json()["results"]), 1)
        self.assertEqual(response.json()["results"][0]["activity"], "update_property")
        self.assertEqual(response.json()["results"][0]["scope"], "Group")
        self.assertEqual(response.json()["results"][0]["item_id"], str(group.pk))
        self.assertEqual(response.json()["results"][0]["detail"]["changes"][0]["type"], "Group")
        self.assertEqual(response.json()["results"][0]["detail"]["changes"][0]["action"], "deleted")
        self.assertEqual(response.json()["results"][0]["detail"]["changes"][0]["before"], "finance")
        self.assertEqual(response.json()["results"][0]["detail"]["changes"][0]["after"], None)

    @freeze_time("2021-05-02")
    def test_group_property_crud_delete_missing_key(self):
        group_type_mapping = create_group_type_mapping_without_created_at(
            team=self.team,
            project_id=self.team.project_id,
            group_type_index=0,
            group_type="organization",
        )
        create_group(
            team_id=self.team.pk,
            group_type_index=typed_group_type_index(group_type_mapping.group_type_index),
            group_key="org:5",
            properties={"industry": "finance", "name": "Mr. Krabs"},
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/groups/delete_property?group_key=org:5&group_type_index=0",
            {},
        )
        self.assertEqual(response.status_code, 400)

    @freeze_time("2021-05-02")
    def test_group_property_crud_delete_invalid_group_key(self):
        group_type_mapping = create_group_type_mapping_without_created_at(
            team=self.team,
            project_id=self.team.project_id,
            group_type_index=0,
            group_type="organization",
        )
        create_group(
            team_id=self.team.pk,
            group_type_index=typed_group_type_index(group_type_mapping.group_type_index),
            group_key="org:5",
            properties={"industry": "finance", "name": "Mr. Krabs"},
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/groups/delete_property?group_key=org:0&group_type_index=0",
            {"$unset": "industry"},
        )
        self.assertEqual(response.status_code, 404)

    def test_delete_property_missing_group_type_index(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/groups/delete_property?group_key=org:5",
            {"$unset": "industry"},
        )
        self.assertEqual(response.status_code, 400)

    def test_delete_property_missing_group_key(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/groups/delete_property?group_type_index=0",
            {"$unset": "industry"},
        )
        self.assertEqual(response.status_code, 400)

    @freeze_time("2021-05-02")
    @patch("ee.clickhouse.views.groups.capture_internal")
    def test_delete_property_nonexistent_property(self, mock_capture):
        mock_capture.return_value = mock.MagicMock(status_code=200)
        create_group_type_mapping_without_created_at(
            team=self.team,
            project_id=self.team.project_id,
            group_type_index=0,
            group_type="organization",
        )
        create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key="org:5",
            properties={"industry": "finance"},
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/groups/delete_property?group_key=org:5&group_type_index=0",
            {"$unset": "nonexistent"},
        )
        self.assertEqual(response.status_code, 400)

    @freeze_time("2021-05-02")
    def test_delete_property_non_string_unset(self):
        create_group_type_mapping_without_created_at(
            team=self.team,
            project_id=self.team.project_id,
            group_type_index=0,
            group_type="organization",
        )
        create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key="org:5",
            properties={"industry": "finance"},
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/groups/delete_property?group_key=org:5&group_type_index=0",
            {"$unset": ["industry"]},
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    @freeze_time("2021-05-02")
    @patch("ee.clickhouse.views.groups.capture_internal")
    def test_get_group_activities_success(self, mock_capture):
        # Mock the response to return a 200 OK
        mock_capture.return_value = mock.MagicMock(status_code=200)

        group_type_mapping = create_group_type_mapping_without_created_at(
            team=self.team,
            project_id=self.team.project_id,
            group_type_index=0,
            group_type="organization",
        )
        group = create_group(
            team_id=self.team.pk,
            group_type_index=typed_group_type_index(group_type_mapping.group_type_index),
            group_key="org:5",
            properties={"industry": "finance", "name": "Mr. Krabs"},
        )

        # Triggers the entry
        response = self.client.post(
            f"/api/projects/{self.team.id}/groups/update_property?group_key=org:5&group_type_index=0",
            {"key": "industry", "value": "technology"},
        )

        self.assertEqual(response.status_code, 200)

        response = self.client.get(
            f"/api/projects/{self.team.id}/groups/activity?group_key=org:5&group_type_index=0",
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("results", response.json())
        self.assertEqual(len(response.json()["results"]), 1)
        self.assertEqual(response.json()["results"][0]["activity"], "update_property")
        self.assertEqual(response.json()["results"][0]["scope"], "Group")
        self.assertEqual(response.json()["results"][0]["item_id"], str(group.pk))
        self.assertEqual(response.json()["results"][0]["detail"]["changes"][0]["type"], "Group")
        self.assertEqual(response.json()["results"][0]["detail"]["changes"][0]["action"], "changed")

    @freeze_time("2021-05-02")
    @patch("ee.clickhouse.views.groups.capture_internal")
    def test_get_group_activities_invalid_group(self, mock_capture):
        # Mock the response to return a 200 OK
        mock_capture.return_value = mock.MagicMock(status_code=200)

        group_type_mapping = create_group_type_mapping_without_created_at(
            team=self.team,
            project_id=self.team.project_id,
            group_type_index=0,
            group_type="organization",
        )
        create_group(
            team_id=self.team.pk,
            group_type_index=typed_group_type_index(group_type_mapping.group_type_index),
            group_key="org:5",
            properties={"industry": "finance", "name": "Mr. Krabs"},
        )

        # Triggers the entry
        response = self.client.post(
            f"/api/projects/{self.team.id}/groups/update_property?group_key=org:5&group_type_index=0",
            {"key": "industry", "value": "technology"},
        )

        self.assertEqual(response.status_code, 200)

        response = self.client.get(
            f"/api/projects/{self.team.id}/groups/activity?group_key=org:5&group_type_index=1",
        )

        self.assertEqual(response.status_code, 404)

    @freeze_time("2021-05-10")
    @snapshot_clickhouse_queries
    def test_related_groups(self):
        self._create_related_groups_data()

        response_data = self.client.get(
            f"/api/projects/{self.team.id}/groups/related?id=0::0&group_type_index=0"
        ).json()
        self.assertEqual(
            response_data,
            [
                {
                    "created_at": "2021-05-10T00:00:00Z",
                    "last_seen_at": None,
                    "distinct_ids": ["1", "2"],
                    "id": "01795392-cc00-0003-7dc7-67a694604d72",
                    "uuid": "01795392-cc00-0003-7dc7-67a694604d72",
                    "is_identified": False,
                    "name": "1",
                    "properties": {},
                    "type": "person",
                    "matched_recordings": [],
                    "value_at_data_point": None,
                },
                {
                    "created_at": "2021-05-10T00:00:00Z",
                    "group_key": "1::2",
                    "group_type_index": 1,
                    "id": "1::2",
                    "properties": {},
                    "type": "group",
                    "matched_recordings": [],
                    "value_at_data_point": None,
                },
                {
                    "created_at": "2021-05-10T00:00:00Z",
                    "group_key": "1::3",
                    "group_type_index": 1,
                    "id": "1::3",
                    "properties": {},
                    "type": "group",
                    "matched_recordings": [],
                    "value_at_data_point": None,
                },
            ],
        )

    @freeze_time("2021-05-10")
    @snapshot_clickhouse_queries
    def test_related_groups_person(self):
        uuid = self._create_related_groups_data()

        response_data = self.client.get(f"/api/projects/{self.team.id}/groups/related?id={uuid}").json()
        self.assertEqual(
            response_data,
            [
                {
                    "created_at": "2021-05-10T00:00:00Z",
                    "group_key": "0::0",
                    "group_type_index": 0,
                    "id": "0::0",
                    "properties": {},
                    "type": "group",
                    "matched_recordings": [],
                    "value_at_data_point": None,
                },
                {
                    "created_at": "2021-05-10T00:00:00Z",
                    "group_key": "0::1",
                    "group_type_index": 0,
                    "id": "0::1",
                    "properties": {},
                    "type": "group",
                    "matched_recordings": [],
                    "value_at_data_point": None,
                },
                {
                    "created_at": "2021-05-10T00:00:00Z",
                    "group_key": "1::2",
                    "group_type_index": 1,
                    "id": "1::2",
                    "properties": {},
                    "type": "group",
                    "matched_recordings": [],
                    "value_at_data_point": None,
                },
                {
                    "created_at": "2021-05-10T00:00:00Z",
                    "group_key": "1::3",
                    "group_type_index": 1,
                    "id": "1::3",
                    "properties": {},
                    "type": "group",
                    "matched_recordings": [],
                    "value_at_data_point": None,
                },
            ],
        )

    def test_related_missing_id(self):
        response = self.client.get(f"/api/projects/{self.team.id}/groups/related?group_type_index=0")
        self.assertEqual(response.status_code, 400)

    def test_property_values(self):
        create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key="org:5",
            properties={"industry": "finance"},
        )
        create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key="org:6",
            properties={"industry": "technology"},
        )
        create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key="org:7",
            properties={"industry": "finance-technology"},
        )
        create_group(
            team_id=self.team.pk,
            group_type_index=1,
            group_key="org:1",
            properties={"industry": "finance"},
        )

        # Test without query parameter
        response_data = self.client.get(
            f"/api/projects/{self.team.id}/groups/property_values/?key=industry&group_type_index=0"
        ).json()["results"]
        self.assertEqual(len(response_data), 3)
        self.assertEqual(
            response_data,
            [
                {"name": "finance", "count": 1},
                {"name": "finance-technology", "count": 1},
                {"name": "technology", "count": 1},
            ],
        )

        # Test with query parameter
        response_data = self.client.get(
            f"/api/projects/{self.team.id}/groups/property_values/?key=industry&group_type_index=0&value=fin"
        ).json()["results"]
        self.assertEqual(len(response_data), 2)
        self.assertEqual(response_data, [{"name": "finance", "count": 1}, {"name": "finance-technology", "count": 1}])

        # Test with query parameter - case insensitive
        response_data = self.client.get(
            f"/api/projects/{self.team.id}/groups/property_values/?key=industry&group_type_index=0&value=TECH"
        ).json()["results"]
        self.assertEqual(len(response_data), 2)
        self.assertEqual(
            response_data, [{"name": "finance-technology", "count": 1}, {"name": "technology", "count": 1}]
        )

        # Test with query parameter - no matches
        response_data = self.client.get(
            f"/api/projects/{self.team.id}/groups/property_values/?key=industry&group_type_index=0&value=healthcare"
        ).json()["results"]
        self.assertEqual(len(response_data), 0)
        self.assertEqual(response_data, [])

        # Test with query parameter - exact match
        response_data = self.client.get(
            f"/api/projects/{self.team.id}/groups/property_values/?key=industry&group_type_index=0&value=technology"
        ).json()["results"]
        self.assertEqual(len(response_data), 2)
        self.assertEqual(
            response_data, [{"name": "finance-technology", "count": 1}, {"name": "technology", "count": 1}]
        )

        # Test with different group_type_index
        response_data = self.client.get(
            f"/api/projects/{self.team.id}/groups/property_values/?key=industry&group_type_index=1&value=fin"
        ).json()["results"]
        self.assertEqual(len(response_data), 1)
        self.assertEqual(response_data, [{"name": "finance", "count": 1}])

    def test_empty_property_values(self):
        create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key="org:5",
            properties={"industry": "finance"},
        )
        create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key="org:6",
            properties={"industry": "technology"},
        )
        create_group(
            team_id=self.team.pk,
            group_type_index=1,
            group_key="org:1",
            properties={"industry": "finance"},
        )
        response_data = self.client.get(
            f"/api/projects/{self.team.id}/groups/property_values/?key=name&group_type_index=0"
        ).json()["results"]
        self.assertEqual(len(response_data), 0)
        self.assertEqual(response_data, [])

    def test_property_values_missing_group_type_index(self):
        response = self.client.get(f"/api/projects/{self.team.id}/groups/property_values/?key=name")
        self.assertEqual(response.status_code, 400)

    def test_property_values_missing_key(self):
        response = self.client.get(f"/api/projects/{self.team.id}/groups/property_values/?group_type_index=0")
        self.assertEqual(response.status_code, 400)

    def test_update_groups_metadata(self):
        create_group_type_mapping_without_created_at(
            team=self.team, project_id=self.team.project_id, group_type="organization", group_type_index=0
        )
        create_group_type_mapping_without_created_at(
            team=self.team, project_id=self.team.project_id, group_type="playlist", group_type_index=1
        )
        create_group_type_mapping_without_created_at(
            team=self.team, project_id=self.team.project_id, group_type="another", group_type_index=2
        )

        response_data = self.client.patch(
            f"/api/projects/{self.team.id}/groups_types/update_metadata",
            [
                {"group_type_index": 0, "name_singular": "organization!"},
                {
                    "group_type_index": 1,
                    "group_type": "rename attempt",
                    "name_plural": "playlists",
                },
            ],
        ).json()

        self.assertEqual(
            response_data,
            [
                {
                    "group_type_index": 0,
                    "group_type": "organization",
                    "name_singular": "organization!",
                    "name_plural": None,
                    "detail_dashboard": None,
                    "default_columns": None,
                    "created_at": None,
                },
                {
                    "group_type_index": 1,
                    "group_type": "playlist",
                    "name_singular": None,
                    "name_plural": "playlists",
                    "detail_dashboard": None,
                    "default_columns": None,
                    "created_at": None,
                },
                {
                    "group_type_index": 2,
                    "group_type": "another",
                    "name_singular": None,
                    "name_plural": None,
                    "detail_dashboard": None,
                    "default_columns": None,
                    "created_at": None,
                },
            ],
        )

    def test_list_group_types(self):
        create_group_type_mapping_without_created_at(
            team=self.team, project_id=self.team.project_id, group_type="organization", group_type_index=0
        )
        create_group_type_mapping_without_created_at(
            team=self.team, project_id=self.team.project_id, group_type="playlist", group_type_index=1
        )
        create_group_type_mapping_without_created_at(
            team=self.team, project_id=self.team.project_id, group_type="another", group_type_index=2
        )

        response_data = self.client.get(f"/api/projects/{self.team.id}/groups_types").json()

        self.assertEqual(
            response_data,
            [
                {
                    "group_type_index": 0,
                    "group_type": "organization",
                    "name_singular": None,
                    "name_plural": None,
                    "detail_dashboard": None,
                    "default_columns": None,
                    "created_at": None,
                },
                {
                    "group_type_index": 1,
                    "group_type": "playlist",
                    "name_singular": None,
                    "name_plural": None,
                    "detail_dashboard": None,
                    "default_columns": None,
                    "created_at": None,
                },
                {
                    "group_type_index": 2,
                    "group_type": "another",
                    "name_singular": None,
                    "name_plural": None,
                    "detail_dashboard": None,
                    "default_columns": None,
                    "created_at": None,
                },
            ],
        )

    def test_cannot_list_group_types_of_another_org(self):
        other_org = Organization.objects.create(name="other org")
        other_team = Team.objects.create(organization=other_org, name="other project")

        create_group_type_mapping_without_created_at(
            team=other_team, project_id=other_team.project_id, group_type="organization", group_type_index=0
        )
        create_group_type_mapping_without_created_at(
            team=other_team, project_id=other_team.project_id, group_type="playlist", group_type_index=1
        )
        create_group_type_mapping_without_created_at(
            team=other_team, project_id=other_team.project_id, group_type="another", group_type_index=2
        )

        response = self.client.get(f"/api/projects/{other_team.id}/groups_types")  # No access to this project

        self.assertEqual(response.status_code, 403, response.json())
        self.assertEqual(
            response.json(),
            self.permission_denied_response("You don't have access to the project."),
        )

    def test_cannot_list_group_types_of_another_org_with_sharing_token(self):
        sharing_configuration = SharingConfiguration.objects.create(team=self.team, enabled=True)

        other_org = Organization.objects.create(name="other org")
        other_team = Team.objects.create(organization=other_org, name="other project")

        create_group_type_mapping_without_created_at(
            team=other_team, project_id=other_team.project_id, group_type="organization", group_type_index=0
        )
        create_group_type_mapping_without_created_at(
            team=other_team, project_id=other_team.project_id, group_type="playlist", group_type_index=1
        )
        create_group_type_mapping_without_created_at(
            team=other_team, project_id=other_team.project_id, group_type="another", group_type_index=2
        )

        response = self.client.get(
            f"/api/projects/{other_team.id}/groups_types/?sharing_access_token={sharing_configuration.access_token}"
        )

        self.assertEqual(response.status_code, 403, response.json())
        self.assertEqual(
            response.json(),
            self.permission_denied_response("You do not have permission to perform this action."),
        )

    def test_can_list_group_types_of_another_org_with_sharing_access_token(self):
        other_org = Organization.objects.create(name="other org")
        other_team = Team.objects.create(organization=other_org, name="other project")
        sharing_configuration = SharingConfiguration.objects.create(team=other_team, enabled=True)

        create_group_type_mapping_without_created_at(
            team=other_team, project_id=other_team.project_id, group_type="organization", group_type_index=0
        )
        create_group_type_mapping_without_created_at(
            team=other_team, project_id=other_team.project_id, group_type="playlist", group_type_index=1
        )
        create_group_type_mapping_without_created_at(
            team=other_team, project_id=other_team.project_id, group_type="another", group_type_index=2
        )

        disabled_response = self.client.get(
            f"/api/projects/{other_team.id}/groups_types/?sharing_access_token={sharing_configuration.access_token}"
        ).json()

        self.assertEqual(
            disabled_response,
            [
                {
                    "group_type_index": 0,
                    "group_type": "organization",
                    "name_singular": None,
                    "name_plural": None,
                    "detail_dashboard": None,
                    "default_columns": None,
                    "created_at": None,
                },
                {
                    "group_type_index": 1,
                    "group_type": "playlist",
                    "name_singular": None,
                    "name_plural": None,
                    "detail_dashboard": None,
                    "default_columns": None,
                    "created_at": None,
                },
                {
                    "group_type_index": 2,
                    "group_type": "another",
                    "name_singular": None,
                    "name_plural": None,
                    "detail_dashboard": None,
                    "default_columns": None,
                    "created_at": None,
                },
            ],
        )

        # Disable the config now
        sharing_configuration.enabled = False
        sharing_configuration.save()

        disabled_response = self.client.get(
            f"/api/projects/{other_team.id}/groups_types?sharing_access_token={sharing_configuration.access_token}"
        )

        self.assertEqual(disabled_response.status_code, 403, disabled_response.json())
        self.assertEqual(
            disabled_response.json(),
            self.unauthenticated_response("Sharing access token is invalid.", "authentication_failed"),
        )

    def test_create_detail_dashboard_success(self):
        create_group_type_mapping_without_created_at(
            team=self.team, project_id=self.team.project_id, group_type="organization", group_type_index=0
        )

        response = self.client.put(
            f"/api/projects/{self.team.id}/groups_types/create_detail_dashboard",
            {"group_type_index": 0},
        )
        self.assertEqual(response.status_code, 200)

        group_type_mapping = get_group_type_mapping_instance(project_id=self.team.project_id, group_type_index=0)
        self.assertIsNotNone(group_type_mapping.detail_dashboard_id)

    def test_create_detail_dashboard_duplicate(self):
        group_type = create_group_type_mapping_without_created_at(
            team=self.team, project_id=self.team.project_id, group_type="organization", group_type_index=0
        )

        dashboard = create_group_type_mapping_detail_dashboard(group_type, self.user)
        update_group_type_mapping_fields(group_type, fields={"detail_dashboard_id": dashboard.id}, caller_tag="test")

        response = self.client.put(
            f"/api/projects/{self.team.id}/groups_types/create_detail_dashboard",
            {"group_type_index": 0},
        )
        self.assertEqual(response.status_code, 400)

    def test_create_detail_dashboard_not_found(self):
        response = self.client.put(
            f"/api/projects/{self.team.id}/groups_types/create_detail_dashboard",
            {"group_type_index": 1},
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json().get("detail"), "Group type not found")

    def test_set_default_columns_success(self):
        create_group_type_mapping_without_created_at(
            team=self.team, project_id=self.team.project_id, group_type="organization", group_type_index=0
        )

        response = self.client.put(
            f"/api/projects/{self.team.id}/groups_types/set_default_columns",
            {"group_type_index": 0, "default_columns": ["$group_0", "$group_1"]},
        )
        self.assertEqual(response.status_code, 200)

        group_type_mapping = get_group_type_mapping_instance(project_id=self.team.project_id, group_type_index=0)
        self.assertEqual(group_type_mapping.default_columns, ["$group_0", "$group_1"])

    def test_set_default_columns_not_found(self):
        response = self.client.put(
            f"/api/projects/{self.team.id}/groups_types/set_default_columns",
            {"group_type_index": 1, "default_columns": ["$group_0", "$group_1"]},
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json().get("detail"), "Group type not found")

    def _create_related_groups_data(self):
        create_group_type_mapping_without_created_at(
            team=self.team, project_id=self.team.project_id, group_type="organization", group_type_index=0
        )
        create_group_type_mapping_without_created_at(
            team=self.team, project_id=self.team.project_id, group_type="playlist", group_type_index=1
        )

        uuid = UUID("01795392-cc00-0003-7dc7-67a694604d72")

        create_person(uuid=uuid, team=self.team, distinct_ids=["1", "2"])
        create_person(team=self.team, distinct_ids=["3"])
        create_person(team=self.team, distinct_ids=["4"])

        create_group(self.team.pk, 0, "0::0")
        create_group(self.team.pk, 0, "0::1")
        create_group(self.team.pk, 1, "1::2")
        create_group(self.team.pk, 1, "1::3")
        create_group(self.team.pk, 1, "1::4")
        create_group(self.team.pk, 1, "1::5")

        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="1",
            timestamp="2021-05-05 00:00:00",
            properties={"$group_0": "0::0", "$group_1": "1::2"},
        )

        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="1",
            timestamp="2021-05-05 00:00:00",
            properties={"$group_0": "0::0", "$group_1": "1::3"},
        )

        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="1",
            timestamp="2021-05-05 00:00:00",
            properties={"$group_0": "0::1", "$group_1": "1::3"},
        )

        # Event too old, not counted
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="1",
            timestamp="2000-05-05 00:00:00",
            properties={"$group_0": "0::0", "$group_1": "1::4"},
        )

        # No such group exists in groups table
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="1",
            timestamp="2000-05-05 00:00:00",
            properties={"$group_0": "0::0", "$group_1": "no such group"},
        )

        return uuid


class GroupsTypesViewSetTestCase(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.url = f"/api/projects/{self.team.id}/groups_types"

    def test_delete(self):
        group_type_data = {
            "team": self.team,
            "project": self.project,
            "group_type": "organization",
            "group_type_index": 0,
        }
        group_type = create_group_type_mapping_without_created_at(**group_type_data)
        delete_url = self.url + f"/{group_type.group_type_index}"

        delete_response = self.client.delete(delete_url)

        self.assertEqual(delete_response.status_code, status.HTTP_204_NO_CONTENT)
        remaining_indices = [m["group_type_index"] for m in get_group_types_for_project(self.team.project_id)]
        self.assertNotIn(group_type.group_type_index, remaining_indices)

        list_response = self.client.get(self.url)

        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(list_response.json()), 0)

    def test_delete_nonexistent(self):
        response = self.client.delete(self.url + "/99")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_create_detail_dashboard(self):
        create_group_type_mapping(team=self.team, project=self.project, group_type="organization", group_type_index=0)

        response = self.client.put(self.url + "/create_detail_dashboard", {"group_type_index": 0})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["group_type"], "organization")
        self.assertEqual(data["group_type_index"], 0)
        self.assertIsNotNone(data["detail_dashboard"])

    def _seed_cache(self):
        """Populate both cache keys with well-formed but stale data so we can verify invalidation."""
        cache_key = f"{GROUP_TYPES_CACHE_KEY_PREFIX}{self.team.project_id}"
        stale_cache_key = f"{GROUP_TYPES_STALE_CACHE_KEY_PREFIX}{self.team.project_id}"
        stale_row = {
            "group_type": "organization",
            "group_type_index": 0,
            "name_singular": None,
            "name_plural": None,
            "detail_dashboard": None,
            "default_columns": None,
            "created_at": None,
        }
        cache.set(cache_key, [stale_row], 300)
        cache.set(stale_cache_key, [stale_row], 300)
        return cache_key, stale_cache_key

    def test_list_serves_from_group_types_cache(self):
        # No GroupTypeMapping rows exist — a response can only come from the cached helper
        cache_key = f"{GROUP_TYPES_CACHE_KEY_PREFIX}{self.team.project_id}"
        cache.set(
            cache_key,
            [
                {
                    "group_type": "organization",
                    "group_type_index": 0,
                    "name_singular": None,
                    "name_plural": None,
                    "detail_dashboard": 7,
                    "default_columns": ["name"],
                    "created_at": None,
                }
            ],
            300,
        )

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.json(),
            [
                {
                    "group_type": "organization",
                    "group_type_index": 0,
                    "name_singular": None,
                    "name_plural": None,
                    "detail_dashboard": 7,
                    "default_columns": ["name"],
                    "created_at": None,
                }
            ],
        )

    def test_list_normalizes_legacy_detail_dashboard_id_cache_key(self):
        # Cache entries written before the personhog converter matched the ORM
        # .values() shape carry "detail_dashboard_id" — the response must still
        # expose "detail_dashboard"
        cache_key = f"{GROUP_TYPES_CACHE_KEY_PREFIX}{self.team.project_id}"
        cache.set(
            cache_key,
            [
                {
                    "group_type": "organization",
                    "group_type_index": 0,
                    "name_singular": None,
                    "name_plural": None,
                    "detail_dashboard_id": 42,
                    "default_columns": None,
                    "created_at": None,
                }
            ],
            300,
        )

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()[0]["detail_dashboard"], 42)
        self.assertNotIn("detail_dashboard_id", response.json()[0])

    def test_update_metadata_invalidates_cache(self):
        create_group_type_mapping(team=self.team, project=self.project, group_type="organization", group_type_index=0)
        cache_key, stale_cache_key = self._seed_cache()

        response = self.client.patch(
            self.url + "/update_metadata",
            [{"group_type_index": 0, "name_singular": "org"}],
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # update_metadata responds with the list, which re-populates both caches with fresh rows
        self.assertEqual(cache.get(cache_key)[0]["name_singular"], "org")
        self.assertEqual(cache.get(stale_cache_key)[0]["name_singular"], "org")

    def test_destroy_invalidates_cache(self):
        create_group_type_mapping(team=self.team, project=self.project, group_type="organization", group_type_index=0)
        cache_key, stale_cache_key = self._seed_cache()

        response = self.client.delete(self.url + "/0")

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertIsNone(cache.get(cache_key))
        self.assertIsNone(cache.get(stale_cache_key))

    def test_create_detail_dashboard_invalidates_cache(self):
        create_group_type_mapping(team=self.team, project=self.project, group_type="organization", group_type_index=0)
        cache_key, stale_cache_key = self._seed_cache()

        response = self.client.put(self.url + "/create_detail_dashboard", {"group_type_index": 0})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(cache.get(cache_key))
        self.assertIsNone(cache.get(stale_cache_key))

    def test_set_default_columns_invalidates_cache(self):
        create_group_type_mapping(team=self.team, project=self.project, group_type="organization", group_type_index=0)
        cache_key, stale_cache_key = self._seed_cache()

        response = self.client.put(
            self.url + "/set_default_columns",
            {"group_type_index": 0, "default_columns": ["name", "email"]},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(cache.get(cache_key))
        self.assertIsNone(cache.get(stale_cache_key))

    def test_update_metadata_non_admin_cannot_modify_protected_fields(self):
        from posthog.constants import AvailableFeature
        from posthog.models.organization import OrganizationMembership

        from ee.models.rbac.access_control import AccessControl

        group_type = create_group_type_mapping(
            team=self.team, project=self.project, group_type="organization", group_type_index=0
        )
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
        ]
        self.organization.save()
        # Grant member-level (not admin) project access so the request reaches the serializer
        AccessControl.objects.create(
            team=self.team,
            resource="project",
            resource_id=str(self.team.id),
            access_level="member",
        )

        response = self.client.patch(
            self.url + "/update_metadata",
            [{"group_type_index": group_type.group_type_index, "name_singular": "Org", "name_plural": "Orgs"}],
            content_type="application/json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        group_type = get_group_type_mapping_instance(
            project_id=self.team.project_id, group_type_index=group_type.group_type_index
        )
        self.assertIsNone(group_type.name_singular)
        self.assertIsNone(group_type.name_plural)

    def test_update_metadata_admin_can_modify_protected_fields(self):
        from posthog.models.organization import OrganizationMembership

        group_type = create_group_type_mapping(
            team=self.team, project=self.project, group_type="organization", group_type_index=0
        )
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        response = self.client.patch(
            self.url + "/update_metadata",
            [{"group_type_index": group_type.group_type_index, "name_singular": "Org", "name_plural": "Orgs"}],
            content_type="application/json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        group_type = get_group_type_mapping_instance(
            project_id=self.team.project_id, group_type_index=group_type.group_type_index
        )
        self.assertEqual(group_type.name_singular, "Org")
        self.assertEqual(group_type.name_plural, "Orgs")


class GroupUsageMetricViewSetTestCase(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.group_type = create_group_type_mapping(
            team=self.team, project=self.project, group_type="organization", group_type_index=0
        )
        self.url = f"/api/projects/{self.team.id}/groups_types/{str(self.group_type.group_type_index)}/metrics"

        self.other_org = Organization.objects.create(name="other org")
        self.other_team = Team.objects.create(organization=self.other_org, name="other team")
        self.other_group_type = create_group_type_mapping(
            team=self.other_team, project_id=self.other_team.project_id, group_type="company", group_type_index=0
        )
        self.other_url = (
            f"/api/projects/{self.other_team.id}/groups_types/{str(self.other_group_type.group_type_index)}/metrics"
        )

    def assertFields(self, data, metric):
        self.assertEqual(data["id"], str(metric.id))
        self.assertEqual(data["name"], metric.name)
        self.assertEqual(data["format"], metric.format)
        self.assertEqual(data["interval"], metric.interval)
        self.assertEqual(data["display"], metric.display)
        self.assertEqual(data["filters"], metric.filters)

    def _create_metric(self, **kwargs):
        defaults = {
            "team": self.team,
            "group_type_index": self.group_type.group_type_index,
            "name": "Events",
            "filters": {"foo": "bar"},
        }
        defaults.update(kwargs)
        return GroupUsageMetric.objects.create(**defaults)

    def test_list(self):
        metric = self._create_metric()

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFields(response.json()["results"][0], metric)

    def test_create(self):
        payload = {"name": "Events", "filters": {"foo": "bar"}}

        response = self.client.post(self.url, payload)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        metric = GroupUsageMetric.objects.get(id=response.json().get("id"))
        self.assertFields(response.json(), metric)
        self.assertEqual(metric.team, self.team, "Should set team automatically")
        self.assertEqual(
            metric.group_type_index, self.group_type.group_type_index, "Should set group_type_index automatically"
        )
        self.assertIsNotNone(metric.bytecode, "Should set bytecode automatically")

    def test_retrieve(self):
        metric = self._create_metric()
        url = f"{self.url}/{metric.id}"

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFields(response.json(), metric)

    def test_update(self):
        metric = self._create_metric()
        url = f"{self.url}/{metric.id}"
        payload = {
            "name": "Updated Events",
            "format": "currency",
            "interval": 30,
            "display": "sparkline",
            "filters": {"updated": "value"},
        }

        response = self.client.put(url, payload)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        metric.refresh_from_db()
        self.assertEqual(metric.name, "Updated Events")
        self.assertEqual(metric.format, "currency")
        self.assertEqual(metric.interval, 30)
        self.assertEqual(metric.display, "sparkline")
        self.assertEqual(metric.filters, {"updated": "value"})
        self.assertFields(response.json(), metric)

    def test_delete(self):
        metric = self._create_metric()
        url = f"{self.url}/{metric.id}"

        response = self.client.delete(url)

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(GroupUsageMetric.objects.filter(id=metric.id).exists())

    def test_partial_update(self):
        metric = self._create_metric()
        url = f"{self.url}/{metric.id}"
        payload = {"name": "Partially Updated Events"}

        response = self.client.patch(url, payload)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        metric.refresh_from_db()
        self.assertEqual(metric.name, "Partially Updated Events")
        self.assertEqual(metric.format, "numeric", "Should remain unchanged")
        self.assertEqual(metric.interval, 7, "Should remain unchanged")
        self.assertEqual(metric.display, "number", "Should remain unchanged")

    def test_delete_nonexistent(self):
        fake_id = "00000000-0000-0000-0000-000000000000"
        url = f"{self.url}/{fake_id}"

        response = self.client.delete(url)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_update_nonexistent(self):
        fake_id = "00000000-0000-0000-0000-000000000000"
        url = f"{self.url}/{fake_id}"
        payload = {"name": "Updated Events"}

        response = self.client.put(url, payload)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_unauthenticated_access(self):
        self.client.logout()

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_unauthorized_team_access(self):
        self._create_metric(group_type_index=self.other_group_type.group_type_index, team=self.other_team)

        response = self.client.get(self.other_url)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.json(), self.permission_denied_response("You don't have access to the project."))

    def test_unauthorized_metric_access(self):
        other_metric = self._create_metric(
            group_type_index=self.other_group_type.group_type_index, team=self.other_team
        )
        url = f"{self.other_url}/{other_metric.id}"

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.json(), self.permission_denied_response("You don't have access to the project."))

    def test_unauthorized_metric_creation(self):
        payload = {"name": "Unauthorized Events"}

        response = self.client.post(self.other_url, payload)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.json(), self.permission_denied_response("You don't have access to the project."))

    def test_unauthorized_metric_modification(self):
        other_metric = self._create_metric(
            group_type_index=self.other_group_type.group_type_index, team=self.other_team
        )
        url = f"{self.other_url}/{other_metric.id}"
        payload = {"name": "Hacked Events"}

        response = self.client.put(url, payload)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.json(), self.permission_denied_response("You don't have access to the project."))

    def test_unauthorized_metric_deletion(self):
        other_metric = self._create_metric(
            group_type_index=self.other_group_type.group_type_index, team=self.other_team
        )
        url = f"{self.other_url}/{other_metric.id}"

        response = self.client.delete(url)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.json(), self.permission_denied_response("You don't have access to the project."))

        self.assertTrue(GroupUsageMetric.objects.filter(id=other_metric.id).exists())

    def test_non_admin_cannot_update_metric(self):
        from posthog.constants import AvailableFeature
        from posthog.models.organization import OrganizationMembership

        from ee.models.rbac.access_control import AccessControl

        metric = self._create_metric()
        url = f"{self.url}/{metric.id}"
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
        ]
        self.organization.save()
        # Grant member-level (not admin) project access so the request reaches the serializer
        AccessControl.objects.create(
            team=self.team,
            resource="project",
            resource_id=str(self.team.id),
            access_level="member",
        )

        response = self.client.patch(url, {"name": "Should not update"})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        metric.refresh_from_db()
        self.assertEqual(metric.name, "Events")

    def test_admin_can_update_metric(self):
        from posthog.models.organization import OrganizationMembership

        metric = self._create_metric()
        url = f"{self.url}/{metric.id}"
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        response = self.client.patch(url, {"name": "Updated by admin"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        metric.refresh_from_db()
        self.assertEqual(metric.name, "Updated by admin")

    def _create_dw_table(self, name: str = "stripe_charges"):
        from products.warehouse_sources.backend.facade.models import DataWarehouseCredential, DataWarehouseTable

        credential = DataWarehouseCredential.objects.create(team=self.team, access_key="key", access_secret="secret")
        return DataWarehouseTable.objects.create(
            team=self.team,
            name=name,
            credential=credential,
            url_pattern="http://example.com/{name}",
            columns={
                "customer_id": {"clickhouse": "String", "hogql": "StringDatabaseField", "valid": True},
                "created": {"clickhouse": "DateTime64(3, 'UTC')", "hogql": "DateTimeDatabaseField", "valid": True},
                "amount": {"clickhouse": "Float64", "hogql": "FloatDatabaseField", "valid": True},
            },
        )

    def test_create_data_warehouse_metric(self):
        self._create_dw_table()
        payload = {
            "name": "DW signups",
            "math": "count",
            "filters": {
                "source": "data_warehouse",
                "table_name": "stripe_charges",
                "timestamp_field": "created",
                "key_field": "customer_id",
            },
        }

        response = self.client.post(self.url, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json())
        metric = GroupUsageMetric.objects.get(id=response.json()["id"])
        self.assertEqual(metric.filters["source"], "data_warehouse")
        self.assertEqual(metric.filters["table_name"], "stripe_charges")

    def test_create_data_warehouse_metric_rejects_missing_fields(self):
        self._create_dw_table()
        payload = {
            "name": "DW signups",
            "filters": {"source": "data_warehouse", "table_name": "stripe_charges"},
        }

        response = self.client.post(self.url, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["attr"], "filters")

    def test_create_data_warehouse_metric_rejects_unknown_table(self):
        payload = {
            "name": "DW signups",
            "filters": {
                "source": "data_warehouse",
                "table_name": "no_such_table",
                "timestamp_field": "created",
                "key_field": "customer_id",
            },
        }

        response = self.client.post(self.url, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["attr"], "filters")

    def test_create_data_warehouse_metric_accepts_table_with_null_deleted(self):
        table = self._create_dw_table()
        table.deleted = None
        table.save()

        payload = {
            "name": "DW signups",
            "filters": {
                "source": "data_warehouse",
                "table_name": "stripe_charges",
                "timestamp_field": "created",
                "key_field": "customer_id",
            },
        }

        response = self.client.post(self.url, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json())

    def test_create_data_warehouse_metric_rejects_soft_deleted_table(self):
        table = self._create_dw_table()
        table.deleted = True
        table.save()

        payload = {
            "name": "DW signups",
            "filters": {
                "source": "data_warehouse",
                "table_name": "stripe_charges",
                "timestamp_field": "created",
                "key_field": "customer_id",
            },
        }

        response = self.client.post(self.url, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["attr"], "filters")

    def test_create_data_warehouse_sum_requires_math_property(self):
        self._create_dw_table()
        payload = {
            "name": "DW revenue",
            "math": "sum",
            "filters": {
                "source": "data_warehouse",
                "table_name": "stripe_charges",
                "timestamp_field": "created",
                "key_field": "customer_id",
            },
        }

        response = self.client.post(self.url, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["attr"], "math_property")

    def test_create_metric_rejects_unknown_source(self):
        payload = {
            "name": "Bogus",
            "filters": {"source": "something_else"},
        }

        response = self.client.post(self.url, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["attr"], "filters")


class GroupPropertyDefinitionsTestCase(ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        super().setUp()
        self.group_type_index: GroupTypeIndex = 0
        self.group_type_mapping = create_group_type_mapping_without_created_at(
            team=self.team,
            project_id=self.team.project_id,
            group_type_index=self.group_type_index,
            group_type="organization",
        )
        self.group_key = "test_company"
        self.base_url = f"/api/projects/{self.team.id}/groups/"

    @mock.patch("ee.clickhouse.views.groups.capture_internal")
    def test_create_group_creates_property_definitions(self, mock_capture):
        data = {
            "group_type_index": self.group_type_index,
            "group_key": self.group_key,
            "group_properties": {"name": "Test Company", "employees": 100, "is_active": True, "revenue": 50000.50},
        }

        response = self.client.post(self.base_url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        mock_capture.assert_called_once()

        property_definitions = PropertyDefinition.objects.filter(
            team=self.team, type=PropertyDefinition.Type.GROUP, group_type_index=self.group_type_index
        )

        self.assertEqual(property_definitions.count(), 4)

        name_prop = property_definitions.get(name="name")
        self.assertEqual(name_prop.property_type, "String")
        self.assertFalse(name_prop.is_numerical)

        employees_prop = property_definitions.get(name="employees")
        self.assertEqual(employees_prop.property_type, "Numeric")
        self.assertTrue(employees_prop.is_numerical)

        is_active_prop = property_definitions.get(name="is_active")
        self.assertEqual(is_active_prop.property_type, "Boolean")
        self.assertFalse(is_active_prop.is_numerical)

        revenue_prop = property_definitions.get(name="revenue")
        self.assertEqual(revenue_prop.property_type, "Numeric")
        self.assertTrue(revenue_prop.is_numerical)

    @mock.patch("ee.clickhouse.views.groups.capture_internal")
    def test_update_property_creates_property_definition(self, mock_capture):
        create_group(
            team_id=self.team.pk,
            group_type_index=self.group_type_index,
            group_key=self.group_key,
            properties={"existing": "value"},
        )

        data = {"key": "new_property", "value": "test_value"}
        response = self.client.post(
            f"{self.base_url}update_property?group_key={self.group_key}&group_type_index={self.group_type_index}",
            data,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_capture.assert_called_once()

        prop_def = PropertyDefinition.objects.filter(
            team=self.team,
            name="new_property",
            type=PropertyDefinition.Type.GROUP,
            group_type_index=self.group_type_index,
        ).first()

        assert prop_def is not None
        self.assertEqual(prop_def.property_type, "String")
        self.assertFalse(prop_def.is_numerical)

    @mock.patch("ee.clickhouse.views.groups.capture_internal")
    def test_update_property_with_different_types(self, mock_capture):
        create_group(
            team_id=self.team.pk, group_type_index=self.group_type_index, group_key=self.group_key, properties={}
        )

        test_cases = [
            ("string_prop", "test", "String", False),
            ("number_prop", 42, "Numeric", True),
            ("float_prop", 3.14, "Numeric", True),
            ("bool_prop", True, "Boolean", False),
            ("bool_string_true", "true", "Boolean", False),
            ("bool_string_false", "false", "Boolean", False),
        ]
        for prop_name, prop_value, expected_type, expected_numerical in test_cases:
            with self.subTest(prop_name):
                mock_capture.reset_mock()
                data = {"key": prop_name, "value": prop_value}
                response = self.client.post(
                    f"{self.base_url}update_property?group_key={self.group_key}&group_type_index={self.group_type_index}",
                    data,
                    format="json",
                )

                self.assertEqual(response.status_code, status.HTTP_200_OK)
                mock_capture.assert_called_once()

                prop_def = PropertyDefinition.objects.get(
                    team=self.team,
                    name=prop_name,
                    type=PropertyDefinition.Type.GROUP,
                    group_type_index=self.group_type_index,
                )

                self.assertEqual(prop_def.property_type, expected_type)
                self.assertEqual(prop_def.is_numerical, expected_numerical)

    @mock.patch("ee.clickhouse.views.groups.capture_internal")
    def test_update_existing_property_definition(self, mock_capture):
        create_group(
            team_id=self.team.pk, group_type_index=self.group_type_index, group_key=self.group_key, properties={}
        )

        string_prop_data = {"key": "test_prop", "value": "string_value"}
        self.client.post(
            f"{self.base_url}update_property?group_key={self.group_key}&group_type_index={self.group_type_index}",
            string_prop_data,
            format="json",
        )

        numerical_prop_data = {"key": "test_prop", "value": 123}
        self.client.post(
            f"{self.base_url}update_property?group_key={self.group_key}&group_type_index={self.group_type_index}",
            numerical_prop_data,
            format="json",
        )

        prop_def = PropertyDefinition.objects.filter(
            team=self.team, name="test_prop", type=PropertyDefinition.Type.GROUP, group_type_index=self.group_type_index
        ).first()

        assert prop_def is not None
        self.assertEqual(prop_def.property_type, "Numeric")
        self.assertTrue(prop_def.is_numerical)

    @mock.patch("ee.clickhouse.views.groups.capture_internal")
    def test_update_property_missing_key(self, mock_capture):
        mock_capture.return_value = mock.MagicMock(status_code=200)
        create_group(
            team_id=self.team.pk, group_type_index=self.group_type_index, group_key=self.group_key, properties={}
        )

        response = self.client.post(
            f"{self.base_url}update_property?group_key={self.group_key}&group_type_index={self.group_type_index}",
            {"value": "something"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    @mock.patch("ee.clickhouse.views.groups.capture_internal")
    def test_update_property_empty_key(self, mock_capture):
        mock_capture.return_value = mock.MagicMock(status_code=200)
        create_group(
            team_id=self.team.pk, group_type_index=self.group_type_index, group_key=self.group_key, properties={}
        )

        response = self.client.post(
            f"{self.base_url}update_property?group_key={self.group_key}&group_type_index={self.group_type_index}",
            {"key": "", "value": "something"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    @mock.patch("ee.clickhouse.views.groups.capture_internal")
    def test_property_definitions_have_correct_group_type_index(self, mock_capture):
        self.group_type_mapping = create_group_type_mapping_without_created_at(
            team=self.team,
            project_id=self.team.project_id,
            group_type_index=1,
            group_type="team",
        )
        data = {"group_type_index": 1, "group_key": "test_key", "group_properties": {"test_prop": "value"}}

        response = self.client.post(self.base_url, data, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        mock_capture.assert_called_once()
        prop_def = PropertyDefinition.objects.get(
            team=self.team, name="test_prop", type=PropertyDefinition.Type.GROUP, group_type_index=1
        )
        self.assertEqual(prop_def.group_type_index, 1)


class TestListGroupsFunction(ClickhouseTestMixin, APIBaseTest):
    @freeze_time("2021-05-03")
    def test_returns_groups_ordered_by_created_at_desc(self):
        with freeze_time("2021-05-01"):
            create_group(team_id=self.team.pk, group_type_index=0, group_key="org:1", properties={})
        with freeze_time("2021-05-02"):
            create_group(team_id=self.team.pk, group_type_index=0, group_key="org:2", properties={})

        result = list_groups(team_id=self.team.pk, group_type_index=0)

        assert len(result.groups) == 2
        assert result.groups[0].group_key == "org:2"
        assert result.groups[1].group_key == "org:1"
        assert result.has_more is False

    @freeze_time("2021-05-04")
    def test_pagination_with_limit(self):
        with freeze_time("2021-05-01"):
            create_group(team_id=self.team.pk, group_type_index=0, group_key="org:1", properties={})
        with freeze_time("2021-05-02"):
            create_group(team_id=self.team.pk, group_type_index=0, group_key="org:2", properties={})
        with freeze_time("2021-05-03"):
            create_group(team_id=self.team.pk, group_type_index=0, group_key="org:3", properties={})

        result = list_groups(team_id=self.team.pk, group_type_index=0, limit=2)

        assert len(result.groups) == 2
        assert result.groups[0].group_key == "org:3"
        assert result.groups[1].group_key == "org:2"
        assert result.has_more is True

    @freeze_time("2021-05-04")
    def test_pagination_cursor_returns_next_page(self):
        with freeze_time("2021-05-01"):
            create_group(team_id=self.team.pk, group_type_index=0, group_key="org:1", properties={})
        with freeze_time("2021-05-02"):
            create_group(team_id=self.team.pk, group_type_index=0, group_key="org:2", properties={})
        with freeze_time("2021-05-03"):
            create_group(team_id=self.team.pk, group_type_index=0, group_key="org:3", properties={})

        page1 = list_groups(team_id=self.team.pk, group_type_index=0, limit=2)
        last = page1.groups[-1]

        page2 = list_groups(
            team_id=self.team.pk,
            group_type_index=0,
            cursor_created_at_us=int(last.created_at.timestamp() * 1_000_000),
            cursor_group_key=last.group_key,
            limit=2,
        )

        assert len(page2.groups) == 1
        assert page2.groups[0].group_key == "org:1"
        assert page2.has_more is False

    @freeze_time("2021-05-04")
    def test_pagination_cursor_breaks_created_at_ties_on_group_key(self):
        # Three groups created at the same instant: keyset pagination must fall back to the
        # group_key tiebreaker (descending) and neither skip nor duplicate a row across pages.
        with freeze_time("2021-05-01"):
            create_group(team_id=self.team.pk, group_type_index=0, group_key="org:a", properties={})
            create_group(team_id=self.team.pk, group_type_index=0, group_key="org:b", properties={})
            create_group(team_id=self.team.pk, group_type_index=0, group_key="org:c", properties={})

        page1 = list_groups(team_id=self.team.pk, group_type_index=0, limit=2)
        assert [g.group_key for g in page1.groups] == ["org:c", "org:b"]
        assert page1.has_more is True

        last = page1.groups[-1]
        page2 = list_groups(
            team_id=self.team.pk,
            group_type_index=0,
            cursor_created_at_us=int(last.created_at.timestamp() * 1_000_000),
            cursor_group_key=last.group_key,
            limit=2,
        )
        assert [g.group_key for g in page2.groups] == ["org:a"]
        assert page2.has_more is False

    @freeze_time("2021-05-03")
    def test_search_escapes_like_wildcards(self):
        # A literal "%" in the search term must match literally, not act as a wildcard.
        create_group(team_id=self.team.pk, group_type_index=0, group_key="org:1", properties={"name": "50% off"})
        create_group(team_id=self.team.pk, group_type_index=0, group_key="org:2", properties={"name": "discount"})

        matched = list_groups(team_id=self.team.pk, group_type_index=0, search="50%")
        assert [g.group_key for g in matched.groups] == ["org:1"]

        # A bare "%" would match every group if treated as a wildcard; escaped, it matches only the
        # group whose properties contain a literal "%" (org:1's "50% off"), proving the escape works.
        literal = list_groups(team_id=self.team.pk, group_type_index=0, search="%")
        assert [g.group_key for g in literal.groups] == ["org:1"]

    @freeze_time("2021-05-03")
    def test_search_filters_by_properties(self):
        create_group(team_id=self.team.pk, group_type_index=0, group_key="org:1", properties={"name": "Acme Corp"})
        create_group(team_id=self.team.pk, group_type_index=0, group_key="org:2", properties={"name": "Beta Inc"})

        result = list_groups(team_id=self.team.pk, group_type_index=0, search="Acme")

        assert len(result.groups) == 1
        assert result.groups[0].group_key == "org:1"

    @freeze_time("2021-05-03")
    def test_search_matches_group_key_exact(self):
        create_group(team_id=self.team.pk, group_type_index=0, group_key="org:alpha", properties={"name": "Alpha"})
        create_group(team_id=self.team.pk, group_type_index=0, group_key="org:beta", properties={"name": "Beta"})

        result = list_groups(team_id=self.team.pk, group_type_index=0, search="org:alpha")

        assert len(result.groups) == 1
        assert result.groups[0].group_key == "org:alpha"

    @freeze_time("2021-05-03")
    def test_group_key_contains_filter(self):
        create_group(team_id=self.team.pk, group_type_index=0, group_key="org:alpha", properties={})
        create_group(team_id=self.team.pk, group_type_index=0, group_key="org:beta", properties={})

        result = list_groups(team_id=self.team.pk, group_type_index=0, group_key_contains="alpha")

        assert len(result.groups) == 1
        assert result.groups[0].group_key == "org:alpha"

    @freeze_time("2021-05-03")
    def test_filters_by_group_type_index(self):
        create_group(team_id=self.team.pk, group_type_index=0, group_key="org:1", properties={})
        create_group(team_id=self.team.pk, group_type_index=1, group_key="company:1", properties={})

        result = list_groups(team_id=self.team.pk, group_type_index=0)

        assert len(result.groups) == 1
        assert result.groups[0].group_key == "org:1"

    @freeze_time("2021-05-03")
    def test_empty_result(self):
        result = list_groups(team_id=self.team.pk, group_type_index=0)

        assert len(result.groups) == 0
        assert result.has_more is False

    @freeze_time("2021-05-03")
    def test_scopes_results_to_team(self):
        # An identically-keyed group under a different team must never surface — the query is
        # team-scoped by HogQL, so this guards against a cross-team leak.
        create_group(team_id=self.team.pk, group_type_index=0, group_key="org:1", properties={})
        raw_create_group_ch(
            team_id=self.team.pk + 100000,
            group_type_index=0,
            group_key="org:1",
            properties={"name": "OTHER TEAM"},
            created_at=now(),
        )

        result = list_groups(team_id=self.team.pk, group_type_index=0)

        assert len(result.groups) == 1
        assert result.groups[0].group_key == "org:1"
        assert result.groups[0].group_properties == {}

    def test_returns_latest_properties_after_update(self):
        # The groups table dedups by argMax(_timestamp); a newer write for the same (index, key)
        # must win and produce a single row — guards the choice of `groups` over `raw_groups`.
        with freeze_time("2021-05-01"):
            create_group(team_id=self.team.pk, group_type_index=0, group_key="org:1", properties={"name": "Old"})
        with freeze_time("2021-05-02"):
            raw_create_group_ch(
                team_id=self.team.pk,
                group_type_index=0,
                group_key="org:1",
                properties={"name": "New"},
                created_at=now(),
            )

        result = list_groups(team_id=self.team.pk, group_type_index=0)

        assert len(result.groups) == 1
        assert result.groups[0].group_properties == {"name": "New"}

    @freeze_time("2021-05-03")
    def test_preserves_complex_property_values(self):
        # Properties survive the ClickHouse string -> json.loads -> dict round-trip with types intact.
        props = {"count": 5, "active": True, "ratio": 1.5, "tags": ["a", "b"], "nested": {"x": 1}, "missing": None}
        create_group(team_id=self.team.pk, group_type_index=0, group_key="org:1", properties=props)

        result = list_groups(team_id=self.team.pk, group_type_index=0)

        assert len(result.groups) == 1
        assert result.groups[0].group_properties == props

    @freeze_time("2021-05-03")
    def test_search_is_case_insensitive(self):
        create_group(team_id=self.team.pk, group_type_index=0, group_key="org:alpha", properties={"name": "Acme Corp"})

        # Properties substring with a lowercased term, and key-exact with an uppercased term.
        by_props = list_groups(team_id=self.team.pk, group_type_index=0, search="acme")
        by_key = list_groups(team_id=self.team.pk, group_type_index=0, search="ORG:ALPHA")

        assert [g.group_key for g in by_props.groups] == ["org:alpha"]
        assert [g.group_key for g in by_key.groups] == ["org:alpha"]

    @freeze_time("2021-05-03")
    def test_search_no_match_returns_empty(self):
        create_group(team_id=self.team.pk, group_type_index=0, group_key="org:1", properties={"name": "Acme"})

        result = list_groups(team_id=self.team.pk, group_type_index=0, search="zzz-no-such-thing")

        assert result.groups == []
        assert result.has_more is False

    @freeze_time("2021-05-04")
    def test_has_more_false_when_result_count_equals_limit(self):
        with freeze_time("2021-05-01"):
            create_group(team_id=self.team.pk, group_type_index=0, group_key="org:1", properties={})
        with freeze_time("2021-05-02"):
            create_group(team_id=self.team.pk, group_type_index=0, group_key="org:2", properties={})

        result = list_groups(team_id=self.team.pk, group_type_index=0, limit=2)

        assert len(result.groups) == 2
        assert result.has_more is False


class TestGroupsListAPIContract(ClickhouseTestMixin, APIBaseTest):
    @freeze_time("2021-05-02")
    def test_response_format_matches_contract(self):
        create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key="org:1",
            properties={"name": "Test"},
        )

        response_data = self.client.get(f"/api/projects/{self.team.id}/groups?group_type_index=0").json()

        assert "next" in response_data
        assert "previous" in response_data
        assert "results" in response_data
        assert response_data["next"] is None
        assert response_data["previous"] is None
        assert len(response_data["results"]) == 1
        result = response_data["results"][0]
        assert result["group_key"] == "org:1"
        assert result["group_type_index"] == 0
        assert result["group_properties"] == {"name": "Test"}
        assert "created_at" in result

    @freeze_time("2021-05-02")
    def test_invalid_group_type_index_returns_400(self):
        response = self.client.get(f"/api/projects/{self.team.id}/groups?group_type_index=abc")
        assert response.status_code == 400

    @freeze_time("2021-05-02")
    def test_cursor_pagination_via_api(self):
        for i in range(3):
            with freeze_time(f"2021-05-0{i + 1}"):
                create_group(
                    team_id=self.team.pk,
                    group_type_index=0,
                    group_key=f"org:{i}",
                    properties={},
                )

        page1 = self.client.get(f"/api/projects/{self.team.id}/groups?group_type_index=0").json()

        assert page1["next"] is None
        assert len(page1["results"]) == 3
        assert page1["results"][0]["group_key"] == "org:2"
        assert page1["results"][-1]["group_key"] == "org:0"

    @freeze_time("2021-05-02")
    def test_cursor_roundtrip(self):
        cursor = _encode_groups_cursor(1620000000000_000, "org:42")
        created_at_us, group_key = _decode_groups_cursor(cursor)

        assert created_at_us == 1620000000000_000
        assert group_key == "org:42"

    @freeze_time("2021-05-02")
    def test_cursor_backward_compat_ms(self):
        cursor = _encode_groups_cursor(1620000000000, "org:42")
        created_at_us, group_key = _decode_groups_cursor(cursor)

        assert created_at_us == 1620000000000_000
        assert group_key == "org:42"

    @freeze_time("2021-05-02")
    def test_old_format_cursor_is_treated_as_no_cursor(self):
        # Pre-deploy cursors encoded the tiebreaker as "i" (PG id) with no "k". The new keyset can't
        # honor that boundary, so the decoder degrades it to no cursor (restart from the first page).
        old_cursor = base64.urlsafe_b64encode(json.dumps({"c": 1620000000000_000, "i": 42}).encode()).decode()

        created_at_us, group_key = _decode_groups_cursor(old_cursor)

        assert created_at_us == 0
        assert group_key == ""

    @freeze_time("2021-05-02")
    def test_invalid_cursor_is_ignored(self):
        create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key="org:1",
            properties={},
        )

        response_data = self.client.get(
            f"/api/projects/{self.team.id}/groups?group_type_index=0&cursor=invalid_cursor"
        ).json()

        assert len(response_data["results"]) == 1

    @freeze_time("2021-05-02")
    def test_find_uses_personhog_routed_lookup(self):
        create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key="org:1",
            properties={"name": "Test"},
        )

        response = self.client.get(f"/api/projects/{self.team.id}/groups/find?group_type_index=0&group_key=org:1")

        assert response.status_code == 200
        data = response.json()
        assert data["group_key"] == "org:1"
        assert data["group_properties"] == {"name": "Test"}

    @freeze_time("2021-05-02")
    def test_find_nonexistent_returns_404(self):
        response = self.client.get(f"/api/projects/{self.team.id}/groups/find?group_type_index=0&group_key=nonexistent")
        assert response.status_code == 404

    @freeze_time("2021-05-02")
    @patch("ee.clickhouse.views.groups.list_groups")
    def test_list_api_has_more_produces_next_url(self, mock_list_groups):
        # The viewset turns a has_more result into a forward cursor in the `next` URL.
        groups = [
            Group(
                team_id=self.team.pk,
                group_type_index=0,
                group_key=f"org:{i}",
                group_properties={},
                created_at=now(),
            )
            for i in range(100)
        ]
        mock_list_groups.return_value = ListGroupsResult(groups=groups, has_more=True)

        response_data = self.client.get(f"/api/projects/{self.team.id}/groups?group_type_index=0").json()

        assert response_data["next"] is not None
        assert "cursor=" in response_data["next"]
        assert "group_type_index=0" in response_data["next"]
        assert len(response_data["results"]) == 100
