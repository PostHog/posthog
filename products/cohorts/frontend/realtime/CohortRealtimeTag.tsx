import { IconBolt } from '@posthog/icons'
import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'

import { CohortRealtimeReadinessApi, CohortRealtimeStateEnumApi } from '../generated/api.schemas'

type TagContent = { label: string; icon?: JSX.Element; explanation: string }

// A tag appears on every cohort feature flags cannot target, and on the realtime ones they can, so
// a bare row means one thing: flags can target this cohort. Every realtime label leads with the
// word, so a row is never read as the daily calculation being unfinished (a bare "Preparing" beside
// a finished calculation reads as the whole cohort not being ready). Only the ready state keeps the
// bolt, which stands for flags seeing changes at once. `static` gets no tag: flags can target it
// and it has nothing else to say. The cohort page carries the state in full.
const TAG_BY_STATE: Partial<Record<CohortRealtimeStateEnumApi, TagContent>> = {
    ready: {
        label: 'Realtime',
        icon: <IconBolt />,
        explanation:
            'A realtime cohort. Feature flags can target it and see membership changes within about a minute. Insights and the member count still update once a day.',
    },
    building: {
        label: 'Realtime · preparing',
        icon: <Spinner textColored />,
        explanation:
            "A realtime cohort. PostHog is still preparing it, so feature flags can't target it yet. Open the cohort to see the progress.",
    },
    rebuilding: {
        label: 'Realtime · preparing',
        icon: <Spinner textColored />,
        explanation:
            "A realtime cohort. The criteria changed, so PostHog is preparing it again and feature flags can't target it until that finishes. Open the cohort to see the progress.",
    },
    needs_attention: {
        label: 'Realtime · unavailable',
        explanation: "A realtime cohort that feature flags can't target yet. Open the cohort for details.",
    },
    daily: {
        label: 'No flag targeting',
        explanation:
            "Feature flags can't target this cohort. Its criteria are matched in the once-a-day calculation, which feature flags can't read.",
    },
}

/** What feature flags can do with a cohort, for list and picker rows where a sentence is too much. */
export function CohortRealtimeTag({
    realtime,
}: {
    realtime: CohortRealtimeReadinessApi | null | undefined
}): JSX.Element | null {
    const realtimeTargetingEnabled = useFeatureFlag('REALTIME_COHORT_FLAG_TARGETING')
    // A state this bundle predates reads as unknown, not as a state it happens to resemble.
    const content = realtime ? TAG_BY_STATE[realtime.state] : undefined
    if (!realtimeTargetingEnabled || !content) {
        return null
    }

    return (
        <Tooltip title={content.explanation}>
            <LemonTag type="muted" size="small" icon={content.icon} data-attr="cohort-realtime-tag">
                {content.label}
            </LemonTag>
        </Tooltip>
    )
}
