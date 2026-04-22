from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest import TestCase
from unittest.mock import MagicMock, patch

from parameterized import parameterized
from rest_framework.exceptions import PermissionDenied

from posthog.api.insight_variable import InsightVariableViewSet, map_stale_to_latest
from posthog.auth import SharingAccessTokenAuthentication
from posthog.models.insight_variable import InsightVariable


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

    def test_create_list_variable_coerces_null_values_to_empty_list(self):
        response = self.client.post(
            f"/api/environments/{self.team.pk}/insight_variables/",
            data={"name": "List Var", "type": "List"},
        )

        assert response.status_code == 201
        assert response.json()["values"] == []

    def test_insight_variable_limit(self):
        # default list call should return up to 500 variables
        response = self.client.get(f"/api/environments/{self.team.pk}/insight_variables/")
        assert response.status_code == 200

        # create 501 variables
        for i in range(501):
            InsightVariable.objects.create(team=self.team, name=f"Test {i}", type="String")

        response = self.client.get(f"/api/environments/{self.team.pk}/insight_variables/")
        assert response.status_code == 200
        assert len(response.json()["results"]) == 500

    @parameterized.expand(
        [
            ("preserves_underscores", "my_var", "my_var"),
            ("strips_special_chars", "Test @#$ Var!", "test__var"),
            ("multiple_spaces", "foo  bar", "foo__bar"),
            (
                "leading_trailing_spaces",
                " spaced ",
                "spaced",
            ),  # DRF CharField strips whitespace before code_name generation
            ("mixed_alphanumeric", "abc123", "abc123"),
        ]
    )
    def test_code_name_generation(self, _name, input_name, expected_code_name):
        response = self.client.post(
            f"/api/environments/{self.team.pk}/insight_variables/",
            data={"name": input_name, "type": "String"},
            content_type="application/json",
        )
        assert response.status_code == 201
        assert response.json()["code_name"] == expected_code_name

    def test_sharing_token_auth_denied(self):
        request = MagicMock()
        request.successful_authenticator = SharingAccessTokenAuthentication()

        viewset = InsightVariableViewSet()
        viewset.request = request
        viewset.kwargs = {}
        viewset.format_kwarg = None

        with patch("rest_framework.viewsets.ModelViewSet.initial"):
            with self.assertRaises(PermissionDenied) as ctx:
                viewset.initial(request)

        assert "sharing authentication" in str(ctx.exception.detail)

    def test_update_variable_name(self):
        variable = InsightVariable.objects.create(team=self.team, name="Original", type="String", code_name="original")
        response = self.client.patch(
            f"/api/environments/{self.team.pk}/insight_variables/{variable.id}/",
            data={"name": "Updated"},
            content_type="application/json",
        )
        assert response.status_code == 200
        assert response.json()["name"] == "Updated"

    def test_update_list_variable_values(self):
        variable = InsightVariable.objects.create(
            team=self.team, name="List Var", type="List", code_name="list_var", values=["a"]
        )
        response = self.client.patch(
            f"/api/environments/{self.team.pk}/insight_variables/{variable.id}/",
            data={"values": ["a", "b", "c"]},
            content_type="application/json",
        )
        assert response.status_code == 200
        assert response.json()["values"] == ["a", "b", "c"]

    def test_update_type_to_list_coerces_null_values(self):
        variable = InsightVariable.objects.create(team=self.team, name="Str Var", type="String", code_name="str_var")
        response = self.client.patch(
            f"/api/environments/{self.team.pk}/insight_variables/{variable.id}/",
            data={"type": "List"},
            content_type="application/json",
        )
        assert response.status_code == 200
        assert response.json()["values"] == []


class TestMapStaleToLatest(TestCase):
    def _make_variable(self, code_name: str) -> InsightVariable:
        var = MagicMock(spec=InsightVariable)
        var.id = uuid4()
        var.code_name = code_name
        return var

    @parameterized.expand(
        [
            (
                "empty_stale_returns_empty",
                {},
                ["var_a", "var_b"],
                [],
            ),
            (
                "matching_code_names_update_ids",
                {"old-id-1": {"code_name": "var_a", "value": 1}},
                ["var_a"],
                ["var_a"],
            ),
            (
                "unmatched_code_names_dropped",
                {"old-id-1": {"code_name": "no_match", "value": 1}},
                ["var_a"],
                [],
            ),
            (
                "mixed_match_and_no_match",
                {
                    "old-id-1": {"code_name": "var_a", "value": 1},
                    "old-id-2": {"code_name": "no_match", "value": 2},
                },
                ["var_a", "var_b"],
                ["var_a"],
            ),
        ]
    )
    def test_map_stale_to_latest(self, _name, stale, latest_code_names, expected_matched_code_names):
        latest_vars = [self._make_variable(cn) for cn in latest_code_names]
        result = map_stale_to_latest(stale, latest_vars)

        result_code_names = [v["code_name"] for v in result.values()]
        assert sorted(result_code_names) == sorted(expected_matched_code_names)

        for v in result.values():
            code_name = v["code_name"]
            matched_var = next(lv for lv in latest_vars if lv.code_name == code_name)
            assert v["variableId"] == str(matched_var.id)

            # original stale values are preserved via spread
            original = next(sv for sv in stale.values() if sv.get("code_name") == code_name)
            for key, val in original.items():
                assert v[key] == val
