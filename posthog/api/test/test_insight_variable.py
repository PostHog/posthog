from posthog.models.insight_variable import InsightVariable
from posthog.test.base import APIBaseTest


class TestInsightVariable(APIBaseTest):
    def test_create_insight_variable(self):
        response = self.client.post(
            f"/api/environments/{self.team.pk}/insight_variables/", data={"name": "Test 1", "type": "String"}
        )

        assert response.status_code == 201

        variable = InsightVariable.objects.get(team_id=self.team.pk)

        assert variable is not None
        assert variable.created_by is not None
        assert variable.created_at is not None
        assert variable.name == "Test 1"
        assert variable.type == "String"
        assert variable.code_name == "test_1"

    def test_no_duplicate_code_names(self):
        InsightVariable.objects.create(team=self.team, name="Test 1", code_name="test_1")

        response = self.client.post(
            f"/api/environments/{self.team.pk}/insight_variables/", data={"name": "Test 1", "type": "String"}
        )

        assert response.status_code == 400

        variable_count = InsightVariable.objects.filter(team_id=self.team.pk).count()

        assert variable_count == 1

    def test_delete_insight_variable(self):
        variable = InsightVariable.objects.create(team=self.team, name="Test Delete", type="String")

        response = self.client.delete(f"/api/environments/{self.team.pk}/insight_variables/{variable.id}/")
        assert response.status_code == 204

        # Verify the variable was deleted
        assert not InsightVariable.objects.filter(id=variable.id).exists()
