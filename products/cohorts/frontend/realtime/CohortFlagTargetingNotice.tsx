import clsx from 'clsx'
import { useValues } from 'kea'

import { IconInfo } from '@posthog/icons'
import { PostHogCaptureOnViewed } from '@posthog/react'

import { isCohortPropertyFilter } from 'lib/components/PropertyFilters/utils'

import { cohortsModel } from '~/models/cohortsModel'
import { AnyPropertyFilter } from '~/types'

import type { CohortRealtimeStateEnumApi } from '../generated/api.schemas'
import { CohortFlagTargetingNoticeRow } from './CohortFlagTargetingNoticeRow'

// Feature flags can target a cohort in any other state, so only these get a row.
const STATES_WITH_ROW: CohortRealtimeStateEnumApi[] = ['off', 'building', 'rebuilding', 'needs_attention', 'daily']

/**
 * Under a condition set, the cohorts it targets that feature flags can't target yet. Quiet rather than a warning,
 * because nothing is wrong: the cohort is not ready yet, or needs turning on.
 */
export function CohortFlagTargetingNotice({
    properties,
    className,
}: {
    properties: AnyPropertyFilter[]
    className?: string
}): JSX.Element | null {
    const { cohortsById } = useValues(cohortsModel)
    // Ids can arrive as strings, and a set can name the same cohort twice.
    const cohortIds = [...new Set(properties.filter(isCohortPropertyFilter).map(({ value }) => Number(value)))]
    const rows = cohortIds.flatMap((cohortId) => {
        const state = cohortsById[cohortId]?.realtime?.state
        return state && STATES_WITH_ROW.includes(state) ? [{ cohortId, state }] : []
    })
    if (rows.length === 0) {
        return null
    }

    return (
        <PostHogCaptureOnViewed
            // pinned: analytics event name and properties, because insights that count impressions read them
            name="cohort-flag-targeting-notice-shown"
            properties={{ states: [...new Set(rows.map(({ state }) => state))] }}
        >
            <div
                role="status"
                className={clsx(
                    'flex items-start gap-2 text-xs p-2 rounded border border-primary bg-surface-secondary text-secondary',
                    className
                )}
                data-attr="cohort-flag-targeting-notice"
            >
                <IconInfo className="text-base shrink-0 text-muted mt-0.5" />
                <div className="flex flex-col gap-2 min-w-0">
                    {rows.map(({ cohortId }) => (
                        <CohortFlagTargetingNoticeRow key={cohortId} cohortId={cohortId} />
                    ))}
                </div>
            </div>
        </PostHogCaptureOnViewed>
    )
}
