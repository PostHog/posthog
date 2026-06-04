from posthog.schema import ProductIntentContext, ProductKey

from posthog.models.product_intent.product_intent import ProductIntent

_VALID_PRODUCT_KEYS: frozenset[str] = frozenset(p.value for p in ProductKey)
_PRIMARY_ONBOARDING_CONTEXT: str = ProductIntentContext.ONBOARDING_PRODUCT_SELECTED___PRIMARY.value


def get_promoted_product_intent(team_id: int) -> str | None:
    """Return the team's promoted onboarding product, or None.

    Backs the experimental sidebar 'Promoted product' entry. Reads from the
    `ProductIntent` Postgres model rather than the `user showed product intent`
    ClickHouse event — the event is now emitted for many non-onboarding contexts
    (e.g. `intent_context = 'feature flag created'`), whereas the model's
    `contexts` dict lets us match the primary-onboarding context directly.

    The query is cheap because it is anchored on the indexed `team_id` FK and a
    team has only a handful of `ProductIntent` rows (one per product, via the
    team+product_type unique constraint) — the `contexts__has_key` JSON predicate
    is evaluated in-memory over those few rows, not via a JSON index. No per-team
    cache needed.

    Caveat: `updated_at` is `auto_now`, so it bumps on *any* context write to a
    product's row, not only primary-onboarding. For a team that selected one
    primary product (the overwhelming common case) this returns that product;
    in the rare case of multiple primary selections it returns whichever row was
    most recently touched. Good enough for an experiment — tighten if it graduates.
    """
    intent = (
        ProductIntent.objects.filter(team_id=team_id, contexts__has_key=_PRIMARY_ONBOARDING_CONTEXT)
        .order_by("-updated_at")
        .values_list("product_type", flat=True)
        .first()
    )
    if intent is None or intent not in _VALID_PRODUCT_KEYS:
        return None
    return intent
