from datetime import timedelta

from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from ee.api.test.base import APILicensedTest


class TestExperimentPhasesValidation(APILicensedTest):
    @parameterized.expand(
        [
            ("empty_list", [], True, None),
            ("none_value", None, True, None),
            (
                "single_open_phase",
                [{"start_date": "2025-01-01T00:00:00+00:00", "end_date": None}],
                True,
                None,
            ),
            (
                "single_closed_phase",
                [
                    {
                        "start_date": "2025-01-01T00:00:00+00:00",
                        "end_date": "2025-02-01T00:00:00+00:00",
                    }
                ],
                True,
                None,
            ),
            (
                "two_contiguous_phases",
                [
                    {
                        "start_date": "2025-01-01T00:00:00+00:00",
                        "end_date": "2025-02-01T00:00:00+00:00",
                    },
                    {"start_date": "2025-02-01T00:00:00+00:00", "end_date": None},
                ],
                True,
                None,
            ),
            (
                "missing_start_date",
                [{"end_date": "2025-02-01T00:00:00+00:00"}],
                False,
                "Phase 0 must have a start_date",
            ),
            (
                "invalid_start_date",
                [{"start_date": "not-a-date", "end_date": None}],
                False,
                "Phase 0 has an invalid start_date",
            ),
            (
                "start_date_in_future",
                [{"start_date": "2099-01-01T00:00:00+00:00", "end_date": None}],
                False,
                "start_date cannot be in the future",
            ),
            (
                "end_before_start",
                [
                    {
                        "start_date": "2025-02-01T00:00:00+00:00",
                        "end_date": "2025-01-01T00:00:00+00:00",
                    }
                ],
                False,
                "Phase 0 end_date must be after start_date",
            ),
            (
                "open_phase_not_last",
                [
                    {"start_date": "2025-01-01T00:00:00+00:00", "end_date": None},
                    {"start_date": "2025-02-01T00:00:00+00:00", "end_date": None},
                ],
                False,
                "Phase 0 must have an end_date (only the last phase can be open)",
            ),
            (
                "non_contiguous_phases",
                [
                    {
                        "start_date": "2025-01-01T00:00:00+00:00",
                        "end_date": "2025-02-01T00:00:00+00:00",
                    },
                    {"start_date": "2025-03-01T00:00:00+00:00", "end_date": None},
                ],
                False,
                "phases must be contiguous",
            ),
            (
                "not_a_list",
                "not a list",
                False,
                "Phases must be a list",
            ),
            (
                "phase_not_object",
                ["not an object"],
                False,
                "Phase 0 must be an object",
            ),
        ]
    )
    def test_validate_phases(self, _name, phases_value, should_pass, expected_error):
        ff_key = f"phase-test-{_name}"
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Phase Validation Test",
                "feature_flag_key": ff_key,
                "parameters": None,
                "filters": {},
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        experiment_id = response.json()["id"]

        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{experiment_id}/",
            {"phases": phases_value},
            format="json",
        )

        if should_pass:
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(response.json()["phases"], phases_value)
        else:
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            response_text = str(response.json())
            self.assertIn(expected_error, response_text)


class TestAddPhaseEndpoint(APILicensedTest):
    def _create_running_experiment(self, key_suffix: str = "") -> dict:
        ff_key = f"phase-endpoint-test{key_suffix}"
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Phase Endpoint Test",
                "feature_flag_key": ff_key,
                "start_date": "2025-01-01T00:00:00+00:00",
                "parameters": None,
                "filters": {},
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        return response.json()

    def test_add_phase_synthesizes_first_phase_when_empty(self):
        experiment = self._create_running_experiment("-synth")

        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/{experiment['id']}/add_phase/",
            {"phase_start_date": "2025-02-01T00:00:00+00:00"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        phases = response.json()["phases"]
        self.assertEqual(len(phases), 2)

        self.assertEqual(phases[0]["start_date"], "2025-01-01T00:00:00+00:00")
        self.assertEqual(phases[0]["end_date"], "2025-02-01T00:00:00+00:00")
        self.assertEqual(phases[0]["name"], "Phase 1")

        self.assertEqual(phases[1]["start_date"], "2025-02-01T00:00:00+00:00")
        self.assertIsNone(phases[1]["end_date"])

    def test_add_phase_closes_previous_and_appends(self):
        experiment = self._create_running_experiment("-append")

        self.client.post(
            f"/api/projects/{self.team.id}/experiments/{experiment['id']}/add_phase/",
            {"phase_start_date": "2025-02-01T00:00:00+00:00"},
            format="json",
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/{experiment['id']}/add_phase/",
            {
                "phase_start_date": "2025-03-01T00:00:00+00:00",
                "name": "Phase 3",
                "reason": "Changed targeting",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        phases = response.json()["phases"]
        self.assertEqual(len(phases), 3)

        self.assertEqual(phases[1]["end_date"], "2025-03-01T00:00:00+00:00")

        self.assertEqual(phases[2]["start_date"], "2025-03-01T00:00:00+00:00")
        self.assertIsNone(phases[2]["end_date"])
        self.assertEqual(phases[2]["name"], "Phase 3")
        self.assertEqual(phases[2]["reason"], "Changed targeting")

    def test_add_phase_rejects_draft_experiment(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Draft Experiment",
                "feature_flag_key": "draft-phase-test",
                "parameters": None,
                "filters": {},
            },
        )
        experiment = response.json()

        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/{experiment['id']}/add_phase/",
            {"phase_start_date": "2025-02-01T00:00:00+00:00"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("draft", str(response.json()).lower())

    def test_add_phase_rejects_completed_experiment(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Completed Experiment",
                "feature_flag_key": "completed-phase-test",
                "start_date": "2025-01-01T00:00:00+00:00",
                "end_date": "2025-02-01T00:00:00+00:00",
                "parameters": None,
                "filters": {},
            },
        )
        experiment = response.json()

        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/{experiment['id']}/add_phase/",
            {"phase_start_date": "2025-01-15T00:00:00+00:00"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("completed", str(response.json()).lower())

    def test_add_phase_rejects_date_before_experiment_start(self):
        experiment = self._create_running_experiment("-before-start")

        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/{experiment['id']}/add_phase/",
            {"phase_start_date": "2024-12-01T00:00:00+00:00"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("after the experiment start date", str(response.json()))

    def test_add_phase_rejects_future_date(self):
        experiment = self._create_running_experiment("-future")
        future_date = (timezone.now() + timedelta(days=1)).isoformat()

        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/{experiment['id']}/add_phase/",
            {"phase_start_date": future_date},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("cannot be in the future", str(response.json()))

    def test_add_phase_rejects_missing_start_date(self):
        experiment = self._create_running_experiment("-missing")

        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/{experiment['id']}/add_phase/",
            {},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("phase_start_date is required", str(response.json()))

    def test_add_phase_rejects_date_before_last_phase_start(self):
        experiment = self._create_running_experiment("-before-last")

        self.client.post(
            f"/api/projects/{self.team.id}/experiments/{experiment['id']}/add_phase/",
            {"phase_start_date": "2025-03-01T00:00:00+00:00"},
            format="json",
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/{experiment['id']}/add_phase/",
            {"phase_start_date": "2025-02-01T00:00:00+00:00"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("after the last phase", str(response.json()))

    def test_phases_field_returned_in_experiment_response(self):
        experiment = self._create_running_experiment("-field")
        self.assertEqual(experiment["phases"], [])

        response = self.client.get(
            f"/api/projects/{self.team.id}/experiments/{experiment['id']}/",
        )
        self.assertEqual(response.json()["phases"], [])


class TestEditPhaseViaPatch(APILicensedTest):
    def _create_experiment_with_phases(self, key_suffix: str = "") -> dict:
        ff_key = f"edit-phase-test{key_suffix}"
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Edit Phase Test",
                "feature_flag_key": ff_key,
                "start_date": "2025-01-01T00:00:00+00:00",
                "parameters": None,
                "filters": {},
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        experiment = response.json()

        self.client.post(
            f"/api/projects/{self.team.id}/experiments/{experiment['id']}/add_phase/",
            {"phase_start_date": "2025-02-01T00:00:00+00:00", "name": "Phase 2"},
            format="json",
        )
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/{experiment['id']}/add_phase/",
            {"phase_start_date": "2025-03-01T00:00:00+00:00", "name": "Phase 3"},
            format="json",
        )
        return response.json()

    @parameterized.expand(
        [
            (
                "edit_name_only",
                {"phase_index": 1, "updates": {"name": "Renamed Phase"}},
                {"check_field": "name", "expected": "Renamed Phase"},
            ),
            (
                "edit_reason_only",
                {"phase_index": 0, "updates": {"reason": "Updated reason"}},
                {"check_field": "reason", "expected": "Updated reason"},
            ),
            (
                "edit_name_and_reason",
                {"phase_index": 2, "updates": {"name": "Final", "reason": "Last push"}},
                {"check_field": "name", "expected": "Final"},
            ),
        ]
    )
    def test_edit_phase_metadata(self, _name, edit_spec, expectation):
        experiment = self._create_experiment_with_phases(f"-meta-{_name}")
        phases = experiment["phases"]
        idx = edit_spec["phase_index"]

        phases[idx] = {**phases[idx], **edit_spec["updates"]}

        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{experiment['id']}/",
            {"phases": phases},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        result_phase = response.json()["phases"][idx]
        self.assertEqual(result_phase[expectation["check_field"]], expectation["expected"])

    def test_edit_start_date_with_cascading_previous_end_date(self):
        experiment = self._create_experiment_with_phases("-cascade-start")
        phases = experiment["phases"]

        new_boundary = "2025-02-15T00:00:00+00:00"
        phases[1]["start_date"] = new_boundary
        phases[0]["end_date"] = new_boundary

        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{experiment['id']}/",
            {"phases": phases},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        result_phases = response.json()["phases"]
        self.assertEqual(result_phases[0]["end_date"], new_boundary)
        self.assertEqual(result_phases[1]["start_date"], new_boundary)

    def test_edit_end_date_with_cascading_next_start_date(self):
        experiment = self._create_experiment_with_phases("-cascade-end")
        phases = experiment["phases"]

        new_boundary = "2025-02-20T00:00:00+00:00"
        phases[1]["end_date"] = new_boundary
        phases[2]["start_date"] = new_boundary

        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{experiment['id']}/",
            {"phases": phases},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        result_phases = response.json()["phases"]
        self.assertEqual(result_phases[1]["end_date"], new_boundary)
        self.assertEqual(result_phases[2]["start_date"], new_boundary)

    def test_reject_start_date_after_end_date(self):
        experiment = self._create_experiment_with_phases("-invalid-order")
        phases = experiment["phases"]

        phases[0]["start_date"] = "2025-03-01T00:00:00+00:00"

        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{experiment['id']}/",
            {"phases": phases},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("end_date must be after start_date", str(response.json()))

    def test_reject_breaking_contiguity(self):
        experiment = self._create_experiment_with_phases("-broken-contiguity")
        phases = experiment["phases"]

        phases[1]["start_date"] = "2025-02-15T00:00:00+00:00"

        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{experiment['id']}/",
            {"phases": phases},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("contiguous", str(response.json()))
