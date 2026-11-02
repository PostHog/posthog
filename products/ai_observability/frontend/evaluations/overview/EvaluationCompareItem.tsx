import { useActions, useValues } from 'kea'

import { IconArrowRight } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import type { EvaluationResultApi } from '../../generated/api.schemas'
import { compactHeadline, describeAttention, isChartable, lastResultDay } from './evaluationOverviewDisplay'
import { evaluationResultDrawerLogic } from './evaluationResultDrawerLogic'
import { evaluationsOverviewLogic } from './evaluationsOverviewLogic'

const ATTENTION_CLASSES: Record<string, string> = {
    errored: 'text-danger',
    worse: 'text-warning-dark',
    silent: 'text-secondary',
}

function caption(row: EvaluationResultApi, timezone: string): string {
    const attention = describeAttention(row, timezone)
    if (attention) {
        return attention
    }
    if (row.gradedCount > 0) {
        return compactHeadline(row)
    }
    if (row.enabled) {
        return 'No results in this range'
    }
    const day = lastResultDay(row, timezone)
    return day ? `Paused, last result ${day}` : 'Paused'
}

export function EvaluationCompareItem({
    row,
    color,
    onToggle,
}: {
    row: EvaluationResultApi
    color: string | undefined
    onToggle: () => void
}): JSX.Element {
    const { timezone } = useValues(evaluationsOverviewLogic)
    const { openDrawer, prefetchDetails } = useActions(evaluationResultDrawerLogic)
    // Without a line to draw, the row opens the results instead.
    const chartable = isChartable(row)
    const [reason] = row.attentionReasons
    const open = (): void => openDrawer(row.id)
    const prefetch = (): void => prefetchDetails(row.id)
    return (
        <li className="flex items-center gap-1">
            <LemonButton
                size="small"
                className="flex-1 min-w-0"
                active={!!color}
                onClick={chartable ? onToggle : open}
                onMouseEnter={chartable ? undefined : prefetch}
                tooltip={chartable ? (color ? 'Hide from the chart' : 'Show on the chart') : 'Show the results'}
                data-attr={reason ? `evaluation-overview-compare-${reason}` : 'evaluation-overview-compare'}
            >
                <span className="flex items-start gap-2 min-w-0 font-normal">
                    <span
                        className={cn(
                            'mt-1.5 inline-block size-2.5 shrink-0 rounded-full',
                            !color && (chartable ? 'border-2 border-muted' : 'border-2 border-dashed border-muted')
                        )}
                        // eslint-disable-next-line react/forbid-dom-props
                        style={color ? { backgroundColor: color } : undefined}
                    />
                    <span className="flex flex-col min-w-0">
                        <span className="font-semibold line-clamp-3 break-words" title={row.name}>
                            {row.name}
                        </span>
                        <span className={cn('text-xs', (reason && ATTENTION_CLASSES[reason]) || 'text-secondary')}>
                            {caption(row, timezone)}
                        </span>
                    </span>
                </span>
            </LemonButton>
            <LemonButton
                size="xsmall"
                icon={<IconArrowRight />}
                tooltip="Show the results"
                onClick={open}
                onMouseEnter={prefetch}
                data-attr="evaluation-overview-compare-open"
            />
        </li>
    )
}
