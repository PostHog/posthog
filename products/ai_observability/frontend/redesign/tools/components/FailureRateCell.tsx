import clsx from 'clsx'

import { Tooltip } from '@posthog/lemon-ui'

import { percentage } from 'lib/utils/numbers'

import { ToolFailureStateApi, type ToolListItemApi } from '../../../generated/api.schemas'

export interface FailureRateCellProps {
    tool: Pick<ToolListItemApi, 'failureRate' | 'failureState' | 'isFailing'>
}

export function FailureRateCell({ tool: { failureRate, failureState, isFailing } }: FailureRateCellProps): JSX.Element {
    if (failureState === ToolFailureStateApi.NotCaptured) {
        return (
            <Tooltip title="No results of this tool were captured in this date range, so its failures can't be counted.">
                <span className="whitespace-nowrap text-secondary">Not captured</span>
            </Tooltip>
        )
    }
    return (
        <span className={clsx('tabular-nums', isFailing && 'font-semibold text-danger')} translate="no">
            {failureRate === null ? null : percentage(failureRate, 1)}
        </span>
    )
}
