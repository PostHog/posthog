// Mock scout scratchpad entries for Storybook. Shaped to look like real fleet memory:
// namespaced keys (`tags:*`, `dedupe:*`, `closed-out:*`, `team-quirk:*`, `baseline:*`),
// prose content read verbatim into prompts, and a mix of timestamps so recency reads well.

import type { ScratchpadEntryApi } from 'products/signals/frontend/generated/api.schemas'

const RUN = '019e64b8-aaaa-7000-8000-000000000001'

function entry(
    key: string,
    content: string,
    {
        daysAgo = 1,
        createdDaysAgo,
        byScout = true,
    }: { daysAgo?: number; createdDaysAgo?: number; byScout?: boolean } = {}
): ScratchpadEntryApi {
    const updated = new Date(Date.UTC(2026, 5, 23, 12, 0, 0) - daysAgo * 86_400_000).toISOString()
    const created = new Date(
        Date.UTC(2026, 5, 23, 12, 0, 0) - (createdDaysAgo ?? daysAgo + 14) * 86_400_000
    ).toISOString()
    return {
        key,
        content,
        created_at: created,
        updated_at: updated,
        created_by_run_id: byScout ? RUN : null,
    }
}

export const scratchpadEntries: ScratchpadEntryApi[] = [
    entry(
        'tags:errors:taxonomy',
        '# Error-tracking tag vocabulary\n\nCategories I emit findings under, evolved over ~6 weeks:\n\n- `checkout-timeout` — Stripe session creation timing out under load\n- `silent-failure` — request returns 200 but the side effect never happened\n- `auth-drop` — session lost after an SSO redirect hop\n- `export-stuck` — async exports that never reach a terminal state\n\nReuse these before coining a new slug. `payment-decline` was merged into `checkout-timeout` — they were the same root cause.',
        { daysAgo: 0, createdDaysAgo: 44 }
    ),
    entry(
        'tags:llm:taxonomy',
        'LLM-analytics categories: `cost-spike`, `token-runaway`, `prompt-regression`, `eval-drop`. `latency` is intentionally *not* a category here — it belongs to the APM scout, not me.',
        { daysAgo: 2, createdDaysAgo: 30 }
    ),
    entry(
        'dedupe:checkout-timeout',
        'Already reported the checkout/Stripe timeout (finding `2c6be0b`, first emitted 2026-05-12). Do not re-emit unless the daily rate climbs back above ~12/day — it was fixed in PR #12002 and has been quiet since.',
        { daysAgo: 1, createdDaysAgo: 42 }
    ),
    entry(
        'dedupe:invite-500',
        'Team-invite 500 on empty recipient rows is tracked (finding `a1b2c3d`). PR #12001 merged a validation fix; treat new occurrences as a regression, not a fresh finding.',
        { daysAgo: 3, createdDaysAgo: 20 }
    ),
    entry(
        'closed-out:experiments',
        'No running experiments on this project across the last 4 runs. Nothing for the experiments scout to chase — close out fast and re-check weekly rather than every 24h.',
        { daysAgo: 1, createdDaysAgo: 10 }
    ),
    entry(
        'team-quirk:staging-noise',
        'This team replays staging traffic into the prod project on weekday mornings (PT). Error spikes 08:00–10:00 PT on weekdays are almost always synthetic — discount them unless they persist past noon.',
        { daysAgo: 5, createdDaysAgo: 38 }
    ),
    entry(
        'baseline:weekly-active-users',
        'WAU baseline ≈ 4.2k, stable ±8% week-over-week since April. A drop below ~3.8k or a jump above ~4.6k is worth a look; smaller swings are noise.',
        { daysAgo: 6, createdDaysAgo: 35 }
    ),
    entry(
        'note-to-self',
        'The `onboarding_completed` event is double-fired on the SDK install step for ~3% of sessions. Factor this in before reporting an onboarding-funnel anomaly — it inflates the step-2 count.',
        { daysAgo: 4, createdDaysAgo: 16, byScout: false }
    ),
]
