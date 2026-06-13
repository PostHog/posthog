from datetime import datetime, timedelta

from posthog.test.base import BaseTest

from django.utils import timezone

from posthog.schema import ProductKey

from posthog.models.product_intent.product_intent import ProductIntent
from posthog.models.product_intent.promoted_product_lookup import get_promoted_product_intent


class TestPromotedProductLookup(BaseTest):
    def _create_intent(
        self,
        product_key: str,
        contexts: dict[str, int] | None = None,
        updated_at: datetime | None = None,
        team=None,
    ) -> ProductIntent:
        intent = ProductIntent.objects.create(
            team=team or self.team,
            product_type=product_key,
            contexts=contexts if contexts is not None else {"onboarding product selected - primary": 1},
        )
        if updated_at is not None:
            # auto_now=True on `updated_at` blocks normal assignment — use a raw update.
            ProductIntent.objects.filter(pk=intent.pk).update(updated_at=updated_at)
            intent.refresh_from_db()
        return intent

    def test_returns_none_when_no_intent_exists(self) -> None:
        assert get_promoted_product_intent(self.team.pk) is None

    def test_returns_product_key_from_primary_intent(self) -> None:
        self._create_intent(ProductKey.SESSION_REPLAY.value)

        assert get_promoted_product_intent(self.team.pk) == "session_replay"

    def test_ignores_intent_without_primary_onboarding_context(self) -> None:
        # Same product, but only ever marked via secondary or a non-onboarding context.
        self._create_intent(
            ProductKey.SESSION_REPLAY.value,
            contexts={"onboarding product selected - secondary": 1, "feature flag created": 1},
        )

        assert get_promoted_product_intent(self.team.pk) is None

    def test_returns_most_recently_updated_primary_intent(self) -> None:
        now = timezone.now()
        self._create_intent(ProductKey.PRODUCT_ANALYTICS.value, updated_at=now - timedelta(days=2))
        self._create_intent(ProductKey.SESSION_REPLAY.value, updated_at=now - timedelta(days=1))
        self._create_intent(ProductKey.WEB_ANALYTICS.value, updated_at=now)

        assert get_promoted_product_intent(self.team.pk) == "web_analytics"

    def test_scopes_by_team(self) -> None:
        other_team = self.organization.teams.create(name="other")
        self._create_intent(ProductKey.SESSION_REPLAY.value)
        self._create_intent(ProductKey.WEB_ANALYTICS.value, team=other_team)

        assert get_promoted_product_intent(self.team.pk) == "session_replay"
        assert get_promoted_product_intent(other_team.pk) == "web_analytics"

    def test_rejects_unknown_product_key(self) -> None:
        # A stray product_type that isn't in the ProductKey enum — defensive guard
        # against schema drift between the model and the enum.
        self._create_intent("not_a_real_product")

        assert get_promoted_product_intent(self.team.pk) is None

    def test_ignores_event_noise_from_other_contexts(self) -> None:
        # The `feature flag created` intent_context emits the same event as
        # primary-onboarding but is unrelated — make sure we don't pick it up.
        self._create_intent(
            ProductKey.FEATURE_FLAGS.value,
            contexts={"feature flag created": 7},
        )
        self._create_intent(
            ProductKey.SESSION_REPLAY.value,
            contexts={"onboarding product selected - primary": 1},
        )

        assert get_promoted_product_intent(self.team.pk) == "session_replay"
