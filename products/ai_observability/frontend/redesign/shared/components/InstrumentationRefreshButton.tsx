import { IconRefresh } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { AIObservabilityInstrumentationCheckEnumApi } from '../../../generated/api.schemas'
import { INSTRUMENTATION_BUSY_REASON } from './InstrumentationCheckRow'

export const INSTRUMENTATION_REFRESH_FAILED = 'Could not refresh the checklist.'

export interface InstrumentationRefreshButtonProps {
    /** Whether the checklist is being read again. */
    refreshing: boolean
    /** Whether the last refresh failed under a checklist already on screen. */
    refreshFailed: boolean
    /** The check whose dismissal or recheck is being saved, if any. */
    pendingCheckKey: AIObservabilityInstrumentationCheckEnumApi | null
    onRefresh: () => void
    size: 'xsmall' | 'small'
    'data-attr': string
}

export function InstrumentationRefreshButton({
    refreshing,
    refreshFailed,
    pendingCheckKey,
    onRefresh,
    size,
    'data-attr': dataAttr,
}: InstrumentationRefreshButtonProps): JSX.Element {
    return (
        <LemonButton
            type="secondary"
            size={size}
            icon={<IconRefresh />}
            loading={refreshing}
            disabledReason={pendingCheckKey !== null ? INSTRUMENTATION_BUSY_REASON : undefined}
            onClick={onRefresh}
            data-attr={dataAttr}
        >
            {refreshFailed ? 'Try again' : 'Refresh'}
        </LemonButton>
    )
}
