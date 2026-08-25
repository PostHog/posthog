import json
import asyncio
from dataclasses import asdict
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from freezegun import freeze_time
from posthog.test.base import APIBaseTest, BaseTest
from unittest.mock import AsyncMock, patch

from rest_framework import status
from temporalio import activity
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.models import OrganizationMembership, Team
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.customer_analytics.backend.logic.account_track_rules import (
    AccountTrackRuleValidationError,
    create_account_track_rule_run,
    get_account_track_rules,
    preview_account_track_rules,
    process_next_account_track_rule_batch,
)
from products.customer_analytics.backend.models import (
    AccountTrackRuleRun,
    AccountTrackRuleRunStatus,
    CustomPropertyValue,
    DisplayType,
    TargetType,
    TeamCustomerAnalyticsConfig,
)
from products.customer_analytics.backend.temporal.account_track_rules import (
    ACCOUNT_TRACK_RULE_WORKFLOW_NAME,
    AccountTrackRuleEvaluationInput,
    AccountTrackRuleEvaluationOutput,
    AccountTrackRuleEvaluationWorkflow,
    account_track_rule_fail_run_activity,
    account_track_rule_workflow_id,
)
from products.customer_analytics.backend.test.factories import create_account, create_custom_property_definition


@pytest.mark.asyncio
async def test_workflow_processes_batches_until_the_run_finishes() -> None:
    calls = 0

    @activity.defn(name="account_track_rule_process_batch_activity")
    async def process_batch(_input: AccountTrackRuleEvaluationInput) -> AccountTrackRuleEvaluationOutput:
        nonlocal calls
        calls += 1
        return AccountTrackRuleEvaluationOutput(
            status="running" if calls == 1 else "completed",
            processed=1_000 * calls,
        )

    @activity.defn(name="account_track_rule_fail_run_activity")
    async def fail_run(_input: AccountTrackRuleEvaluationInput) -> None:
        raise AssertionError("The success path must not mark the run failed")

    input = AccountTrackRuleEvaluationInput(team_id=1, run_id=str(uuid4()), config_version=3)
    async with await WorkflowEnvironment.start_time_skipping() as environment:
        async with Worker(
            environment.client,
            task_queue="account-track-rules-test",
            workflows=[AccountTrackRuleEvaluationWorkflow],
            activities=[process_batch, fail_run],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            result = await environment.client.execute_workflow(
                ACCOUNT_TRACK_RULE_WORKFLOW_NAME,
                asdict(input),
                id=f"account-track-rules-test-{uuid4()}",
                task_queue="account-track-rules-test",
            )

    assert result == {"status": "completed", "processed": 2_000}
    assert calls == 2


@pytest.mark.asyncio
async def test_workflow_marks_the_run_failed_when_cancelled() -> None:
    input = AccountTrackRuleEvaluationInput(team_id=1, run_id=str(uuid4()), config_version=3)
    execute_activity = AsyncMock(side_effect=[asyncio.CancelledError(), None])

    with (
        patch(
            "products.customer_analytics.backend.temporal.account_track_rules.workflow.execute_activity",
            execute_activity,
        ),
        pytest.raises(asyncio.CancelledError),
    ):
        await AccountTrackRuleEvaluationWorkflow().run(input)

    assert execute_activity.await_count == 2
    assert execute_activity.await_args_list[1].args[0] is account_track_rule_fail_run_activity


def track_rules_config(*, version: int, definition_id: str, enabled: bool = True) -> dict:
    return {
        "schema_version": 1,
        "version": version,
        "enabled": enabled,
        "groups": [
            {
                "conditions": [
                    {
                        "field": {"kind": "custom_property", "definition_id": definition_id},
                        "operator": "gt",
                        "values": [0],
                    },
                    {
                        "field": {"kind": "account_field", "field": "name"},
                        "operator": "exact",
                        "values": ["Paying"],
                    },
                ]
            },
            {
                "conditions": [
                    {
                        "field": {"kind": "account_field", "field": "name"},
                        "operator": "exact",
                        "values": ["VIP"],
                    }
                ]
            },
        ],
    }


class AccountTrackRulesTestMixin:
    team: Team

    def create_rule_fixtures(self):
        definition = create_custom_property_definition(
            team_id=self.team.id,
            name="MRR",
            display_type=DisplayType.CURRENCY,
        )
        paying = create_account(team_id=self.team.id, name="Paying", external_id="paying-workspace")
        vip = create_account(
            team_id=self.team.id,
            name="VIP",
            external_id="vip-workspace",
            ignored_at=datetime(2025, 1, 1, tzinfo=UTC),
        )
        unmatched = create_account(team_id=self.team.id, name="Unmatched", external_id="unmatched-workspace")
        ignored = create_account(
            team_id=self.team.id,
            name="Already ignored",
            external_id="ignored-workspace",
            ignored_at=datetime(2025, 1, 2, tzinfo=UTC),
        )
        churned = create_account(
            team_id=self.team.id,
            name="VIP",
            external_id="churned-workspace",
            churned_at=datetime(2025, 1, 3, tzinfo=UTC),
            ignored_at=datetime(2025, 1, 4, tzinfo=UTC),
        )
        CustomPropertyValue.objects.unscoped().create(
            team=self.team,
            account=paying,
            definition=definition,
            value_num=100,
        )
        return definition, paying, vip, unmatched, ignored, churned

    def save_config(self, config: dict) -> None:
        TeamCustomerAnalyticsConfig.objects.filter(team_id=self.team.id).update(account_track_rules=config)


@freeze_time("2026-08-20T12:00:00Z")
class TestAccountTrackRuleLogic(AccountTrackRulesTestMixin, BaseTest):
    def test_config_defaults_to_a_disabled_empty_version(self) -> None:
        config = TeamCustomerAnalyticsConfig.objects.get(team_id=self.team.id).account_track_rules

        assert config == {"schema_version": 1, "version": 0, "enabled": False, "groups": []}

    def test_preview_uses_or_groups_and_skips_churned_accounts(self) -> None:
        definition, paying, vip, unmatched, ignored, churned = self.create_rule_fixtures()
        self.save_config(track_rules_config(version=3, definition_id=str(definition.id)))

        preview = preview_account_track_rules(self.team.id)

        assert preview.config_version == 3
        assert preview.eligible_active == 4
        assert preview.skipped_churned == 1
        assert preview.tracked == 2
        assert preview.ignored == 2
        assert preview.newly_ignored == 1
        assert preview.restored == 1
        assert {sample.id for sample in preview.tracked_samples} == {paying.id, vip.id}
        assert {sample.id for sample in preview.ignored_samples} == {unmatched.id, ignored.id}
        paying_sample = next(sample for sample in preview.tracked_samples if sample.id == paying.id)
        assert paying_sample.external_id == "paying-workspace"
        assert paying_sample.rule_values == {
            f"custom_property:{definition.id}": 100.0,
            "account_field:name": "Paying",
        }
        vip_sample = next(sample for sample in preview.tracked_samples if sample.id == vip.id)
        assert vip_sample.rule_values == {
            f"custom_property:{definition.id}": None,
            "account_field:name": "VIP",
        }
        churned.refresh_from_db()
        assert churned.ignored_at == datetime(2025, 1, 4, tzinfo=UTC)

    def test_apply_batches_preserve_ignored_timestamps_and_restore_matches(self) -> None:
        definition, paying, vip, unmatched, ignored, churned = self.create_rule_fixtures()
        original_ignored_at = ignored.ignored_at
        original_churned_ignored_at = churned.ignored_at
        self.save_config(track_rules_config(version=3, definition_id=str(definition.id)))
        run = AccountTrackRuleRun.objects.unscoped().create(
            team=self.team,
            config_version=3,
            idempotency_key=uuid4(),
            created_by=self.user,
        )

        while True:
            result = process_next_account_track_rule_batch(self.team.id, run.id, batch_size=2)
            if result.status != AccountTrackRuleRunStatus.RUNNING:
                break

        run.refresh_from_db()
        paying.refresh_from_db()
        vip.refresh_from_db()
        unmatched.refresh_from_db()
        ignored.refresh_from_db()
        churned.refresh_from_db()
        assert run.status == AccountTrackRuleRunStatus.COMPLETED
        assert (run.eligible_active, run.skipped_churned) == (4, 1)
        assert (run.tracked, run.ignored, run.newly_ignored, run.restored) == (2, 2, 1, 1)
        assert paying.ignored_at is None
        assert vip.ignored_at is None
        assert unmatched.ignored_at == datetime(2026, 8, 20, 12, 0, tzinfo=UTC)
        assert ignored.ignored_at == original_ignored_at
        assert churned.ignored_at == original_churned_ignored_at

        no_change_run = AccountTrackRuleRun.objects.unscoped().create(
            team=self.team,
            config_version=3,
            idempotency_key=uuid4(),
            created_by=self.user,
        )
        while (
            process_next_account_track_rule_batch(self.team.id, no_change_run.id, batch_size=2).status
            == AccountTrackRuleRunStatus.RUNNING
        ):
            pass
        no_change_run.refresh_from_db()
        ignored.refresh_from_db()
        assert (no_change_run.newly_ignored, no_change_run.restored) == (0, 0)
        assert ignored.ignored_at == original_ignored_at

        churned.churned_at = None
        churned.save(update_fields=["churned_at"])
        reactivation_run = AccountTrackRuleRun.objects.unscoped().create(
            team=self.team,
            config_version=3,
            idempotency_key=uuid4(),
            created_by=self.user,
        )
        while (
            process_next_account_track_rule_batch(self.team.id, reactivation_run.id, batch_size=2).status
            == AccountTrackRuleRunStatus.RUNNING
        ):
            pass
        churned.refresh_from_db()
        assert churned.ignored_at is None

    def test_config_change_marks_run_stale_before_later_batches(self) -> None:
        definition, paying, vip, unmatched, ignored, churned = self.create_rule_fixtures()
        self.save_config(track_rules_config(version=3, definition_id=str(definition.id)))
        run = AccountTrackRuleRun.objects.unscoped().create(
            team=self.team,
            config_version=3,
            idempotency_key=uuid4(),
            created_by=self.user,
        )

        first = process_next_account_track_rule_batch(self.team.id, run.id, batch_size=1)
        assert first.status == AccountTrackRuleRunStatus.RUNNING
        config = track_rules_config(version=4, definition_id=str(definition.id))
        self.save_config(config)
        for account in [paying, vip, unmatched, ignored, churned]:
            account.refresh_from_db()
        states_before = {account.id: account.ignored_at for account in [paying, vip, unmatched, ignored, churned]}

        second = process_next_account_track_rule_batch(self.team.id, run.id, batch_size=1)

        assert second.status == AccountTrackRuleRunStatus.STALE
        run.refresh_from_db()
        assert run.status == AccountTrackRuleRunStatus.STALE
        for account in [paying, vip, unmatched, ignored, churned]:
            account.refresh_from_db()
            assert account.ignored_at == states_before[account.id]

    def test_deleted_or_wrong_target_definitions_fail_before_writes(self) -> None:
        definition, paying, vip, unmatched, ignored, churned = self.create_rule_fixtures()
        self.save_config(track_rules_config(version=3, definition_id=str(definition.id)))
        definition.delete()
        initial_states = {account.id: account.ignored_at for account in [paying, vip, unmatched, ignored, churned]}

        assert len(get_account_track_rules(self.team.id).groups) == 2
        with pytest.raises(AccountTrackRuleValidationError):
            preview_account_track_rules(self.team.id)

        for account in [paying, vip, unmatched, ignored, churned]:
            account.refresh_from_db()
            assert account.ignored_at == initial_states[account.id]

    def test_lifecycle_fields_are_rejected(self) -> None:
        for field in ["ignored_at", "churned_at"]:
            with self.subTest(field=field):
                config = {
                    "schema_version": 1,
                    "version": 0,
                    "enabled": False,
                    "groups": [
                        {
                            "conditions": [
                                {
                                    "field": {"kind": "account_field", "field": field},
                                    "operator": "is_set",
                                    "values": [],
                                }
                            ]
                        }
                    ],
                }
                self.save_config(config)

                with pytest.raises(AccountTrackRuleValidationError):
                    preview_account_track_rules(self.team.id)

    def test_negative_custom_property_operator_includes_unset_values(self) -> None:
        definition, paying, vip, unmatched, ignored, churned = self.create_rule_fixtures()
        self.save_config(
            {
                "schema_version": 1,
                "version": 1,
                "enabled": True,
                "groups": [
                    {
                        "conditions": [
                            {
                                "field": {"kind": "custom_property", "definition_id": str(definition.id)},
                                "operator": "is_not",
                                "values": [100],
                            }
                        ]
                    }
                ],
            }
        )

        preview = preview_account_track_rules(self.team.id)

        assert preview.tracked == 3
        assert preview.ignored == 1
        assert {sample.id for sample in preview.tracked_samples} == {vip.id, unmatched.id, ignored.id}
        assert preview.ignored_samples[0].id == paying.id

    def test_rejects_cross_team_and_non_account_definitions(self) -> None:
        other_team = Team.objects.create(organization=self.organization)
        other_definition = create_custom_property_definition(team_id=other_team.id, name="Other MRR")
        person_definition = create_custom_property_definition(
            team_id=self.team.id,
            name="Person plan",
            target_type=TargetType.PERSON,
        )

        for definition_id in [other_definition.id, person_definition.id]:
            with self.subTest(definition_id=definition_id):
                self.save_config(track_rules_config(version=1, definition_id=str(definition_id)))
                with pytest.raises(AccountTrackRuleValidationError):
                    preview_account_track_rules(self.team.id)

    def test_rejects_unknown_operators_and_excessive_limits(self) -> None:
        definition = create_custom_property_definition(
            team_id=self.team.id,
            name="MRR",
            display_type=DisplayType.CURRENCY,
        )
        valid_condition = {
            "field": {"kind": "account_field", "field": "name"},
            "operator": "exact",
            "values": ["Acme"],
        }
        invalid_configs = [
            {
                "schema_version": 2,
                "version": 1,
                "enabled": False,
                "groups": [],
            },
            {
                "schema_version": 1,
                "version": 1,
                "enabled": False,
                "groups": [{"conditions": [valid_condition]}] * 21,
            },
            {
                "schema_version": 1,
                "version": 1,
                "enabled": False,
                "groups": [{"conditions": [valid_condition] * 21}],
            },
            {
                "schema_version": 1,
                "version": 1,
                "enabled": False,
                "groups": [{"conditions": [{**valid_condition, "values": ["a"] * 101}]}],
            },
            {
                "schema_version": 1,
                "version": 1,
                "enabled": False,
                "groups": [{"conditions": [{**valid_condition, "values": ["a" * 1_001]}]}],
            },
            {
                "schema_version": 1,
                "version": 1,
                "enabled": False,
                "groups": [{"conditions": [{**valid_condition, "operator": "gt"}]}],
            },
            {
                "schema_version": 1,
                "version": 1,
                "enabled": False,
                "groups": [
                    {
                        "conditions": [
                            {
                                "field": {"kind": "custom_property", "definition_id": str(definition.id)},
                                "operator": "icontains",
                                "values": ["secret"],
                            }
                        ]
                    }
                ],
            },
        ]

        for config in invalid_configs:
            with self.subTest(config=config):
                self.save_config(config)
                with pytest.raises(AccountTrackRuleValidationError):
                    preview_account_track_rules(self.team.id)

    def test_run_creation_is_idempotent_and_workflow_id_is_per_team(self) -> None:
        definition, *_ = self.create_rule_fixtures()
        self.save_config(track_rules_config(version=3, definition_id=str(definition.id)))
        key = uuid4()

        first, first_created = create_account_track_rule_run(
            team_id=self.team.id,
            idempotency_key=key,
            user_id=self.user.id,
        )
        second, second_created = create_account_track_rule_run(
            team_id=self.team.id,
            idempotency_key=key,
            user_id=self.user.id,
        )

        assert first_created is True
        assert second_created is False
        assert first.id == second.id
        assert AccountTrackRuleRun.objects.for_team(self.team.id).count() == 1
        assert account_track_rule_workflow_id(self.team.id) == f"customer-analytics-account-track-rules-{self.team.id}"


@patch("posthog.permissions.posthog_feature_flag_enabled", return_value=True)
class TestAccountTrackRuleAPI(AccountTrackRulesTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save(update_fields=["level"])
        self.url = f"/api/projects/{self.team.id}/account_track_rules"

    def _token(self, scopes: list[str]) -> str:
        value = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="track-rules",
            user=self.user,
            secure_value=hash_key_value(value),
            scopes=scopes,
            scoped_teams=[],
            scoped_organizations=[],
        )
        return value

    def test_admin_can_save_without_changing_accounts_and_stale_save_conflicts(self, _flag) -> None:
        definition, paying, vip, unmatched, ignored, churned = self.create_rule_fixtures()
        initial_states = {account.id: account.ignored_at for account in [paying, vip, unmatched, ignored, churned]}
        config = track_rules_config(version=0, definition_id=str(definition.id), enabled=False)

        with patch(
            "products.customer_analytics.backend.presentation.views.views.report_user_action"
        ) as report_user_action:
            response = self.client.put(self.url, config, format="json")

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["version"] == 1
        assert ActivityLog.objects.filter(
            team_id=self.team.id,
            scope="TeamCustomerAnalyticsConfig",
            activity="updated",
        ).exists()
        event_properties = report_user_action.call_args.args[2]
        assert event_properties == {
            "schema_version": 1,
            "config_version": 1,
            "enabled": False,
            "group_count": 2,
            "condition_count": 3,
        }
        serialized_properties = json.dumps(event_properties)
        assert str(definition.id) not in serialized_properties
        assert "Paying" not in serialized_properties
        for account in [paying, vip, unmatched, ignored, churned]:
            account.refresh_from_db()
            assert account.ignored_at == initial_states[account.id]

        saved_config = response.json()
        assert saved_config["groups"][0]["conditions"][0]["field"] == {
            "kind": "custom_property",
            "definition_id": str(definition.id),
        }
        echoed_payload = json.loads(json.dumps(saved_config))
        echoed_payload["groups"][0]["conditions"][0]["field"]["field"] = None
        echoed_payload["groups"][0]["conditions"][1]["field"]["definition_id"] = None
        echoed_response = self.client.put(self.url, echoed_payload, format="json")
        assert echoed_response.status_code == status.HTTP_200_OK, echoed_response.json()
        assert echoed_response.json()["version"] == 1

        stale_response = self.client.put(self.url, config, format="json")
        assert stale_response.status_code == status.HTTP_409_CONFLICT

    def test_preview_accepts_an_unsaved_draft_without_persisting_it(self, _flag) -> None:
        definition, _, _, unmatched, _, _ = self.create_rule_fixtures()
        saved_config = track_rules_config(version=3, definition_id=str(definition.id))
        self.save_config(saved_config)
        draft_config = {
            "schema_version": 1,
            "version": 3,
            "enabled": True,
            "groups": [
                {
                    "conditions": [
                        {
                            "field": {"kind": "account_field", "field": "name"},
                            "operator": "exact",
                            "values": ["Unmatched"],
                        }
                    ]
                }
            ],
        }

        response = self.client.post(f"{self.url}/preview", draft_config, format="json")

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["tracked"] == 1
        assert response.json()["tracked_samples"] == [
            {
                "id": str(unmatched.id),
                "name": "Unmatched",
                "external_id": "unmatched-workspace",
                "rule_values": {"account_field:name": "Unmatched"},
            }
        ]
        assert TeamCustomerAnalyticsConfig.objects.get(team_id=self.team.id).account_track_rules == saved_config

    def test_api_token_scopes_separate_reads_from_writes(self, _flag) -> None:
        read_token = self._token(["customer_analytics:read"])
        headers = {"authorization": f"Bearer {read_token}"}
        assert self.client.get(self.url, headers=headers).status_code == status.HTTP_200_OK
        assert self.client.get(f"{self.url}/runs", headers=headers).status_code == status.HTTP_200_OK
        assert (
            self.client.put(
                self.url,
                {"schema_version": 1, "version": 0, "enabled": False, "groups": []},
                format="json",
                headers=headers,
            ).status_code
            == status.HTTP_403_FORBIDDEN
        )
        assert (
            self.client.post(f"{self.url}/preview", {}, format="json", headers=headers).status_code
            == status.HTTP_403_FORBIDDEN
        )

        write_token = self._token(["customer_analytics:write"])
        response = self.client.put(
            self.url,
            {"schema_version": 1, "version": 0, "enabled": False, "groups": []},
            format="json",
            headers={"authorization": f"Bearer {write_token}"},
        )
        assert response.status_code == status.HTTP_200_OK, response.json()
        preview = self.client.post(
            f"{self.url}/preview",
            {},
            format="json",
            headers={"authorization": f"Bearer {write_token}"},
        )
        assert preview.status_code == status.HTTP_200_OK, preview.json()

    def test_common_project_payload_omits_track_rules(self, _flag) -> None:
        response = self.client.get(f"/api/projects/{self.team.id}")

        assert response.status_code == status.HTTP_200_OK
        assert "account_track_rules" not in response.json()["customer_analytics_config"]

    def test_feature_flag_blocks_the_surface(self, _flag) -> None:
        with patch("posthog.permissions.posthog_feature_flag_enabled", return_value=False):
            assert self.client.get(self.url).status_code == status.HTTP_403_FORBIDDEN
            assert self.client.post(f"{self.url}/preview", {}, format="json").status_code == status.HTTP_403_FORBIDDEN

    def test_viewer_can_read_but_cannot_change_preview_or_run(self, _flag) -> None:
        definition, *_ = self.create_rule_fixtures()
        self.save_config(track_rules_config(version=3, definition_id=str(definition.id)))
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save(update_fields=["level"])

        assert self.client.get(self.url).status_code == status.HTTP_200_OK
        assert self.client.get(f"{self.url}/runs").status_code == status.HTTP_200_OK
        assert (
            self.client.put(
                self.url,
                track_rules_config(version=3, definition_id=str(definition.id)),
                format="json",
            ).status_code
            == status.HTTP_403_FORBIDDEN
        )
        assert self.client.post(f"{self.url}/preview", {}, format="json").status_code == status.HTTP_403_FORBIDDEN
        assert (
            self.client.post(
                f"{self.url}/run",
                {
                    "idempotency_key": str(uuid4()),
                    "confirmed": True,
                },
                format="json",
            ).status_code
            == status.HTTP_403_FORBIDDEN
        )

    def test_temporal_connection_failure_marks_run_failed(self, _flag) -> None:
        definition, *_ = self.create_rule_fixtures()
        self.save_config(track_rules_config(version=3, definition_id=str(definition.id)))

        with patch("posthog.temporal.common.client.sync_connect", side_effect=ConnectionError("unavailable")):
            response = self.client.post(
                f"{self.url}/run",
                {"idempotency_key": str(uuid4()), "confirmed": True},
                format="json",
            )

        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        run = AccountTrackRuleRun.objects.for_team(self.team.id).get()
        assert run.status == AccountTrackRuleRunStatus.FAILED
        assert run.finished_at is not None

    def test_overlapping_run_is_rejected_and_recorded(self, _flag) -> None:
        definition, *_ = self.create_rule_fixtures()
        self.save_config(track_rules_config(version=3, definition_id=str(definition.id)))
        client = AsyncMock()
        client.start_workflow.side_effect = WorkflowAlreadyStartedError("workflow", "track-rules")

        with patch("posthog.temporal.common.client.sync_connect", return_value=client):
            response = self.client.post(
                f"{self.url}/run",
                {
                    "idempotency_key": str(uuid4()),
                    "confirmed": True,
                },
                format="json",
            )

        assert response.status_code == status.HTTP_409_CONFLICT
        run = AccountTrackRuleRun.objects.for_team(self.team.id).get()
        assert run.status == AccountTrackRuleRunStatus.FAILED
        assert run.error == "The Track Rules run failed. Try again or inspect Error Tracking."

    def test_run_requires_enabled_saved_rules_and_confirmation_but_not_a_preview(self, _flag) -> None:
        definition, *_ = self.create_rule_fixtures()
        disabled_config = track_rules_config(version=3, definition_id=str(definition.id), enabled=False)
        self.save_config(disabled_config)

        disabled = self.client.post(
            f"{self.url}/run",
            {"idempotency_key": str(uuid4()), "confirmed": True},
            format="json",
        )
        assert disabled.status_code == status.HTTP_400_BAD_REQUEST

        enabled_config = {**disabled_config, "enabled": True}
        self.save_config(enabled_config)
        unconfirmed = self.client.post(
            f"{self.url}/run",
            {"idempotency_key": str(uuid4()), "confirmed": False},
            format="json",
        )
        assert unconfirmed.status_code == status.HTTP_400_BAD_REQUEST

        client = AsyncMock()
        with patch("posthog.temporal.common.client.sync_connect", return_value=client):
            started = self.client.post(
                f"{self.url}/run",
                {"idempotency_key": str(uuid4()), "confirmed": True},
                format="json",
            )
        assert started.status_code == status.HTTP_202_ACCEPTED, started.json()
        assert started.json()["status"] == AccountTrackRuleRunStatus.PENDING
        assert started.json()["config_version"] == 3
        client.start_workflow.assert_awaited_once()
