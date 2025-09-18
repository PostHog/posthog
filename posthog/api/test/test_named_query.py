from typing import Any

from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from rest_framework import status

from posthog.models.insight_variable import InsightVariable
from posthog.models.named_query import NamedQuery
from posthog.models.team import Team
from posthog.models.user import User


class TestNamedQuery(ClickhouseTestMixin, APIBaseTest):
    ENDPOINT = "named_query"

    def setUp(self):
        super().setUp()
        self.sample_query = {
            "explain": None,
            "filters": None,
            "kind": "HogQLQuery",
            "modifiers": None,
            "name": None,
            "query": "SELECT count(1) FROM query_log",
            "response": None,
            "tags": None,
            "values": None,
            "variables": None,
            "version": None,
        }

    def test_create_named_query(self):
        """Test creating a named query successfully."""
        data = {
            "name": "test_query",
            "description": "Test query description",
            "query": self.sample_query,
        }

        response = self.client.post(f"/api/environments/{self.team.id}/named_query/", data, format="json")

        self.assertEqual(status.HTTP_201_CREATED, response.status_code, response.json())
        response_data = response.json()

        self.assertEqual("test_query", response_data["name"])
        self.assertEqual(self.sample_query, response_data["query"])
        self.assertEqual("Test query description", response_data["description"])
        self.assertTrue(response_data["is_active"])
        self.assertIn("id", response_data)
        self.assertIn("endpoint_path", response_data)
        self.assertIn("created_at", response_data)
        self.assertIn("updated_at", response_data)

        # Verify it was saved to database
        named_query = NamedQuery.objects.get(name="test_query", team=self.team)
        self.assertEqual(named_query.query, self.sample_query)
        self.assertEqual(named_query.created_by, self.user)

    def test_update_named_query(self):
        """Test updating an existing named query."""
        # Create initial query
        named_query = NamedQuery.objects.create(
            name="update_test",
            team=self.team,
            query=self.sample_query,
            description="Original description",
            created_by=self.user,
        )

        # Update it
        updated_data = {
            "description": "Updated description",
            "is_active": False,
            "query": {"kind": "HogQLQuery", "query": "SELECT 1"},
        }

        response = self.client.put(
            f"/api/environments/{self.team.id}/named_query/{named_query.name}/", updated_data, format="json"
        )

        response_data = response.json()
        self.assertEqual(status.HTTP_200_OK, response.status_code, response_data)

        self.assertEqual("update_test", response_data["name"])
        self.assertEqual("Updated description", response_data["description"])
        self.assertFalse(response_data["is_active"])
        want_query = {
            "explain": None,
            "filters": None,
            "kind": "HogQLQuery",
            "modifiers": None,
            "name": None,
            "query": "SELECT 1",
            "response": None,
            "tags": None,
            "values": None,
            "variables": None,
            "version": None,
        }
        self.assertEqual(want_query, response_data["query"])

        # Verify database was updated
        named_query.refresh_from_db()
        self.assertEqual(named_query.description, "Updated description")
        self.assertFalse(named_query.is_active)

    def test_delete_named_query(self):
        """Test deleting a named query."""

        # Create query to delete
        NamedQuery.objects.create(
            name="delete_test",
            team=self.team,
            query=self.sample_query,
            created_by=self.user,
        )

        response = self.client.delete(f"/api/environments/{self.team.id}/named_query/delete_test/")

        self.assertIn(response.status_code, [status.HTTP_204_NO_CONTENT, status.HTTP_200_OK])

    def test_execute_named_query(self):
        """Test executing a named query successfully."""
        # Create a simple query
        NamedQuery.objects.create(
            name="execute_test",
            team=self.team,
            query={"kind": "HogQLQuery", "query": "SELECT 1 as result"},
            created_by=self.user,
            is_active=True,
        )

        response = self.client.get(f"/api/environments/{self.team.id}/named_query/execute_test/run/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()

        # Verify response structure (should match query response format)
        self.assertIn("results", response_data)
        self.assertIsInstance(response_data["results"], list)

    def test_execute_inactive_query(self):
        """Test that inactive queries cannot be executed."""
        # Create an inactive query
        NamedQuery.objects.create(
            name="inactive_test",
            team=self.team,
            query=self.sample_query,
            created_by=self.user,
            is_active=False,
        )

        response = self.client.get(f"/api/environments/{self.team.id}/named_query/inactive_test/run/")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_invalid_query_name_validation(self):
        """Test validation of invalid query names."""
        # Test invalid characters
        data = {
            "name": "invalid@name!",
            "query": self.sample_query,
        }

        response = self.client.post(f"/api/environments/{self.team.id}/named_query/", data, format="json")

        self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)

    def test_missing_required_fields(self):
        """Test validation when required fields are missing."""
        # Missing name
        data: dict[str, Any] = {"query": self.sample_query}

        response = self.client.post(f"/api/environments/{self.team.id}/named_query/", data, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        # Missing query
        data = {"name": "test_query"}

        response = self.client.post(f"/api/environments/{self.team.id}/named_query/", data, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_duplicate_name_in_team(self):
        """Test that duplicate names within the same team are not allowed."""
        # Create first query
        NamedQuery.objects.create(
            name="duplicate_test",
            team=self.team,
            query=self.sample_query,
            created_by=self.user,
        )

        # Try to create another with same name
        data = {
            "name": "duplicate_test",
            "query": {"kind": "HogQLQuery", "query": "SELECT 2"},
        }

        response = self.client.post(f"/api/environments/{self.team.id}/named_query/", data, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_team_isolation(self):
        """Test that queries are properly isolated between teams."""
        # Create another team and user
        other_team = Team.objects.create(organization=self.organization, name="Other Team")
        other_user = User.objects.create_and_join(self.organization, "other@test.com", None)

        # Create query in other team
        NamedQuery.objects.create(
            name="other_team_query",
            team=other_team,
            query=self.sample_query,
            created_by=other_user,
        )

        # Try to access it from current team - should return 404
        response = self.client.get(f"/api/environments/{self.team.id}/named_query/other_team_query/run/")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_execute_query_with_invalid_sql(self):
        """Test error handling when executing query with invalid SQL."""
        # Create query with invalid SQL
        NamedQuery.objects.create(
            name="invalid_sql_test",
            team=self.team,
            query={"kind": "HogQLQuery", "query": "SELECT FROM invalid_syntax"},
            created_by=self.user,
            is_active=True,
        )

        response = self.client.get(f"/api/environments/{self.team.id}/named_query/invalid_sql_test/run/")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("detail", response.json())

    def test_execute_query_with_variables(self):
        """Test executing a named query with variables."""
        # Create an insight variable first
        variable = InsightVariable.objects.create(
            team=self.team,
            name="From Date",
            code_name="from_date",
            type=InsightVariable.Type.DATE,
            default_value="2025-01-01",
        )

        # Create a query with variables
        query_with_variables = {
            "kind": "HogQLQuery",
            "query": "select * from events where toDate(timestamp) > {variables.from_date} limit 1",
            "variables": {
                str(variable.id): {"variableId": str(variable.id), "code_name": "from_date", "value": "2025-01-01"}
            },
        }

        NamedQuery.objects.create(
            name="query_with_variables",
            team=self.team,
            query=query_with_variables,
            created_by=self.user,
            is_active=True,
        )

        # Execute with variable values
        request_data = {"variables_values": {"from_date": "2025-09-18"}}

        response = self.client.post(
            f"/api/environments/{self.team.id}/named_query/query_with_variables/run/", request_data, format="json"
        )

        response_data = response.json()
        self.assertEqual(response.status_code, status.HTTP_200_OK, response_data)
        self.assertIn("results", response_data)

    def test_list_filter_by_is_active(self):
        """Test filtering named queries by is_active status."""
        # Create active and inactive queries
        NamedQuery.objects.create(
            name="active_query",
            team=self.team,
            query=self.sample_query,
            created_by=self.user,
            is_active=True,
        )
        NamedQuery.objects.create(
            name="inactive_query",
            team=self.team,
            query=self.sample_query,
            created_by=self.user,
            is_active=False,
        )

        # Test filtering for active queries
        response = self.client.get(f"/api/environments/{self.team.id}/named_query/?is_active=true")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertEqual(len(response_data["results"]), 1)
        self.assertEqual(response_data["results"][0]["name"], "active_query")
        self.assertTrue(response_data["results"][0]["is_active"])

        # Test filtering for inactive queries
        response = self.client.get(f"/api/environments/{self.team.id}/named_query/?is_active=false")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertEqual(len(response_data["results"]), 1)
        self.assertEqual(response_data["results"][0]["name"], "inactive_query")
        self.assertFalse(response_data["results"][0]["is_active"])

    def test_list_filter_by_created_by(self):
        """Test filtering named queries by created_by user."""
        # Create another user
        other_user = User.objects.create_and_join(self.organization, "other@test.com", None)

        # Create queries by different users
        NamedQuery.objects.create(
            name="query_by_user1",
            team=self.team,
            query=self.sample_query,
            created_by=self.user,
        )
        NamedQuery.objects.create(
            name="query_by_user2",
            team=self.team,
            query=self.sample_query,
            created_by=other_user,
        )

        # Test filtering by first user
        response = self.client.get(f"/api/environments/{self.team.id}/named_query/?created_by={self.user.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertEqual(len(response_data["results"]), 1)
        self.assertEqual(response_data["results"][0]["name"], "query_by_user1")

        # Test filtering by second user
        response = self.client.get(f"/api/environments/{self.team.id}/named_query/?created_by={other_user.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertEqual(len(response_data["results"]), 1)
        self.assertEqual(response_data["results"][0]["name"], "query_by_user2")

    def test_list_filter_combined(self):
        """Test filtering named queries by both is_active and created_by."""
        # Create another user
        other_user = User.objects.create_and_join(self.organization, "other@test.com", None)

        # Create queries with different combinations
        NamedQuery.objects.create(
            name="active_query_user1",
            team=self.team,
            query=self.sample_query,
            created_by=self.user,
            is_active=True,
        )
        NamedQuery.objects.create(
            name="inactive_query_user1",
            team=self.team,
            query=self.sample_query,
            created_by=self.user,
            is_active=False,
        )
        NamedQuery.objects.create(
            name="active_query_user2",
            team=self.team,
            query=self.sample_query,
            created_by=other_user,
            is_active=True,
        )

        # Test combined filtering
        response = self.client.get(
            f"/api/environments/{self.team.id}/named_query/?is_active=true&created_by={self.user.id}"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertEqual(len(response_data["results"]), 1)
        self.assertEqual(response_data["results"][0]["name"], "active_query_user1")
        self.assertTrue(response_data["results"][0]["is_active"])

    def test_list_no_filters(self):
        """Test listing all named queries without filters."""
        # Create multiple queries
        NamedQuery.objects.create(
            name="query1",
            team=self.team,
            query=self.sample_query,
            created_by=self.user,
            is_active=True,
        )
        NamedQuery.objects.create(
            name="query2",
            team=self.team,
            query=self.sample_query,
            created_by=self.user,
            is_active=False,
        )

        # Test without any filters - should return all queries
        response = self.client.get(f"/api/environments/{self.team.id}/named_query/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertEqual(len(response_data["results"]), 2)
        query_names = {q["name"] for q in response_data["results"]}
        self.assertEqual(query_names, {"query1", "query2"})
