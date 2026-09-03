from posthog.test.base import BaseTest

from django.db import IntegrityError, transaction

from parameterized import parameterized

from products.ai_observability.backend.models.instrumentation_checklist import AIObservabilityChecklistItemState


class TestAIObservabilityChecklistItemState(BaseTest):
    def _dismiss(self, check_key: str = "sessions", scope: str | None = None) -> AIObservabilityChecklistItemState:
        return AIObservabilityChecklistItemState.objects.unscoped().create(
            team=self.team,
            check_key=check_key,
            scope=scope,
            status=AIObservabilityChecklistItemState.Status.DISMISSED,
        )

    @parameterized.expand(
        [
            ("project_wide", None, "uniq_llma_checklist_item_state_global"),
            ("scoped", "chat", "uniq_llma_checklist_item_state"),
        ]
    )
    def test_duplicate_check_key_is_rejected(self, _name: str, scope: str | None, constraint: str) -> None:
        self._dismiss(scope=scope)

        with self.assertRaises(IntegrityError) as caught, transaction.atomic():
            self._dismiss(scope=scope)

        # Quoted so the project-wide case cannot pass on the three-field constraint's name,
        # which is a prefix of the partial constraint's.
        assert f'unique constraint "{constraint}"' in str(caught.exception)

    def test_same_check_key_allowed_across_scopes(self) -> None:
        self._dismiss(scope=None)
        self._dismiss(scope="chat")

        assert AIObservabilityChecklistItemState.objects.for_team(self.team.id).count() == 2
