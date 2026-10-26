import { useActions, useValues } from 'kea'

import { IconClockRewind } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import type { EvaluationResultApi } from '../../generated/api.schemas'
import { evaluationResultDrawerLogic } from './evaluationResultDrawerLogic'
import { evaluationsOverviewLogic } from './evaluationsOverviewLogic'

/** Offers a backfill for a chart line broken into single points by buckets without results. */
export function EvaluationBackfillHint({
    row,
    source,
    named = false,
}: {
    row: EvaluationResultApi
    source: 'drawer' | 'compare_chart'
    named?: boolean
}): JSX.Element {
    const { configById, interval, evaluationUrl } = useValues(evaluationsOverviewLogic)
    const { trackBackfillHint } = useActions(evaluationResultDrawerLogic)
    const config = configById.get(row.id)

    return (
        <div className="flex flex-wrap items-center gap-x-2 text-xs text-secondary">
            <span>
                {named ? <strong className="text-primary">{row.name}</strong> : 'This evaluation'}
                {` has ${interval}s with no results, so some points have no line.`}
            </span>
            <LemonButton
                size="xsmall"
                type="tertiary"
                icon={<IconClockRewind />}
                to={evaluationUrl(row.id, { evaluation_tab: 'backfills' })}
                onClick={() => trackBackfillHint(source)}
                disabledReason={getAccessControlDisabledReason(
                    AccessControlResourceType.Evaluation,
                    AccessControlLevel.Editor,
                    config?.user_access_level ?? undefined
                )}
                data-attr="evaluation-overview-backfill-hint"
            >
                Run on past data
            </LemonButton>
        </div>
    )
}
