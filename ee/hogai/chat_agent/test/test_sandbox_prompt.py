from contextlib import contextmanager
from typing import Any

import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import patch

from asgiref.sync import async_to_sync

from posthog.schema import MaxBillingContext, MaxBillingContextSettings, MaxBillingContextSubscriptionLevel

from posthog.models.group_type_mapping import GROUP_TYPE_MAPPING_SERIALIZER_FIELDS, GroupTypeMapping
from posthog.models.organization import OrganizationMembership
from posthog.test.test_utils import create_group_type_mapping_without_created_at

from ee.hogai.chat_agent.sandbox_prompt import build_posthog_ai_system_prompt


def _billing_context() -> MaxBillingContext:
    return MaxBillingContext(
        has_active_subscription=True,
        products=[],
        settings=MaxBillingContextSettings(active_destinations=0, autocapture_on=False),
        subscription_level=MaxBillingContextSubscriptionLevel.PAID,
    )


@pytest.mark.usefixtures("unittest_snapshot")
class TestSandboxPrompt(APIBaseTest):
    snapshot: object

    def _create_groups(self) -> None:
        create_group_type_mapping_without_created_at(
            team=self.team, project_id=self.team.project_id, group_type="organization", group_type_index=0
        )
        create_group_type_mapping_without_created_at(
            team=self.team, project_id=self.team.project_id, group_type="instance", group_type_index=1
        )

    @contextmanager
    def _groups_resolve(self):
        # In tests the personhog-routed `get_group_types_for_project` returns [] for ORM-created
        # mappings (it reads from a store that doesn't see the freshly-inserted rows), so the prompt
        # builder never sees the groups. Patch the routed helper to return the rows we actually
        # created — this is what production resolves to when personhog and the ORM agree.
        rows: list[dict[str, Any]] = list(
            GroupTypeMapping.objects.filter(project_id=self.team.project_id)
            .order_by("group_type_index")
            .values(*GROUP_TYPE_MAPPING_SERIALIZER_FIELDS)
        )
        with patch("posthog.models.group_type_mapping.get_group_types_for_project", return_value=rows):
            yield

    def _set_membership_level(self, level: OrganizationMembership.Level) -> None:
        membership = OrganizationMembership.objects.get(organization=self.organization, user=self.user)
        membership.level = level
        membership.save()

    def test_baseline_with_groups_and_billing_access(self) -> None:
        self._create_groups()
        self._set_membership_level(OrganizationMembership.Level.ADMIN)
        with self._groups_resolve():
            prompt = async_to_sync(build_posthog_ai_system_prompt)(
                self.team, self.user, context_summary={"billing_context": _billing_context()}
            )
        # Assert the rendered groups block literally — a snapshot would silently pass even with an
        # empty <groups> slot (the original regression), so check the content directly.
        assert "<groups>" in prompt
        assert "The user has defined the following groups: organization, instance." in prompt
        assert "</groups>" in prompt

    def test_no_groups_with_billing_access(self) -> None:
        self._set_membership_level(OrganizationMembership.Level.ADMIN)
        prompt = async_to_sync(build_posthog_ai_system_prompt)(
            self.team, self.user, context_summary={"billing_context": _billing_context()}
        )
        assert prompt == self.snapshot

    def test_billing_no_access(self) -> None:
        self._create_groups()
        self._set_membership_level(OrganizationMembership.Level.MEMBER)
        prompt = async_to_sync(build_posthog_ai_system_prompt)(
            self.team, self.user, context_summary={"billing_context": _billing_context()}
        )
        assert prompt == self.snapshot

    def test_billing_error_access_but_no_context(self) -> None:
        self._create_groups()
        self._set_membership_level(OrganizationMembership.Level.ADMIN)
        prompt = async_to_sync(build_posthog_ai_system_prompt)(self.team, self.user)
        assert prompt == self.snapshot

    def test_no_plan_mode_or_core_memory_blocks(self) -> None:
        self._set_membership_level(OrganizationMembership.Level.ADMIN)
        prompt = async_to_sync(build_posthog_ai_system_prompt)(self.team, self.user)
        assert "plan_mode" not in prompt
        assert "core_memory" not in prompt
        assert "switching_modes" not in prompt

    def test_billing_access_check_failure_degrades_to_no_access(self) -> None:
        # A user with no organization membership row raises in check_user_has_billing_access; the
        # builder must degrade to the no-access variant rather than crash the Run-create path.
        OrganizationMembership.objects.filter(organization=self.organization, user=self.user).delete()
        prompt = async_to_sync(build_posthog_ai_system_prompt)(
            self.team, self.user, context_summary={"billing_context": _billing_context()}
        )
        assert "does not have admin access" in prompt
