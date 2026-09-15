import { IconBolt } from '@posthog/icons'
import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'

import { CohortRealtimeReadinessApi, CohortRealtimeStateEnumApi } from '../generated/api.schemas'

type TagContent = { label: string; icon: JSX.Element; explanation: string }

// Every label leads with "Realtime" so a row is never read as the daily calculation being unfinished:
// a bare "Preparing" beside a finished calculation reads as the whole cohort not being ready. The
// cohort page carries the state in full. `daily` and `static` get no tag, because a tag on every row
// would drown the few that matter.
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
        label: 'Realtime',
        icon: <IconBolt />,
        explanation: "A realtime cohort that feature flags can't target yet. Open the cohort for details.",
    },
}

/** Marks a realtime cohort in the list and picker rows, where a sentence would be too much. */
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
            <LemonTag type="muted" size="small" icon={content.icon}>
                {content.label}
            </LemonTag>
        </Tooltip>
    )
}
