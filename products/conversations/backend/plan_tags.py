# The support team's plan/priority tiering, derived from ticket tags. Group
# order IS the priority order (index 0 = Triage = highest). A ticket takes the
# highest-priority group with a matching tag; tickets with no matching tag
# rank with Triage (they still need routing).
#
# MUST stay in lockstep with the frontend copy in
# products/conversations/frontend/scenes/tickets/planTags.ts (the column's
# labels live there; ranks here). Tag vocabulary sources: the "Customer and
# account tags" section of https://posthog.com/handbook/support/posthog-support,
# the live SLA workflow's tags, and the Zendesk import's tag names.
from django.db.models import Case, Exists, IntegerField, OuterRef, Value, When

# rank → exact tag names (no prefix matching)
PLAN_GROUP_TAGS: list[list[str]] = [
    ["support_needs_triage"],  # 0 Triage (also the untagged fallback)
    ["churn_risk"],  # 1 Churn risk
    ["plan_top20", "top_20"],  # 2 Top 20
    [  # 3 Enterprise
        "plan_enterprise",
        "goodwill_enterprise",
        "unknown_slack_default_enterprise",
        "unknown_msteams_default_enterprise",
    ],
    ["plan_onboarding", "new_customer_onboarding"],  # 4 Onboarding
    ["plan_scale", "plan_teams_legacy", "plan_teams", "plan_yc"],  # 5 Scale & Teams & YC
    [  # 6 Boost & Startup & Pay-as-you-go paying
        "plan_boost",
        "plan_startup",
        "plan_pay-as-you-go_paying",
        "plan_pay-as-you-go",
        "plan_paid",
    ],
    ["plan_pay-as-you-go_free"],  # 7 Pay-as-you-go free
    ["plan_free"],  # 8 Free plan
    ["community"],  # 9 Community
]


def plan_rank_annotation() -> Case:
    """A per-ticket plan rank for ORDER BY: the first (highest-priority) group
    with a matching tag wins, courtesy of Case evaluating Whens in order.
    Untagged/unmatched tickets take the default rank 0 (Triage).

    Perf note: this is one correlated EXISTS per group (10 today). Each can be
    served by TaggedItem's partial unique index on (tag, ticket) probed
    tag-first (the group's tag ids are few), but there is no ticket-leading
    index — if staff usage makes this sort hot at scale, consider adding one.
    """
    from posthog.models.tagged_item import TaggedItem

    return Case(
        *[
            When(
                Exists(TaggedItem.objects.filter(ticket=OuterRef("pk"), tag__name__in=tags)),
                then=Value(rank),
            )
            for rank, tags in enumerate(PLAN_GROUP_TAGS)
        ],
        default=Value(0),
        output_field=IntegerField(),
    )
