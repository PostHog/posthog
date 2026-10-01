import { useValues } from 'kea'

import { IconVideoCamera } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import 'lib/components/LiveUserCount/LiveUserCount.scss'
import { cn } from 'lib/utils/css-classes'
import { humanFriendlyLargeNumber } from 'lib/utils/numbers'
import { pluralize } from 'lib/utils/strings'

import { liveRecordingsCountLogic } from './liveRecordingsCountLogic'

export function LiveRecordingsCount(): JSX.Element | null {
    const { activeRecordings } = useValues(liveRecordingsCountLogic)

    if (activeRecordings === null) {
        return null
    }

    const hasRecordings = activeRecordings > 0

    return (
        <Tooltip title="Session recordings currently in progress." placement="right">
            <div
                className={cn(
                    'flex items-center gap-1.5 px-2 py-1 rounded-md transition-colors',
                    hasRecordings ? 'bg-success-highlight' : 'bg-border-light'
                )}
            >
                <div className={cn('live-user-indicator', hasRecordings ? 'online' : 'offline')} />
                <IconVideoCamera className="size-4 shrink-0 min-[660px]:hidden" />
                <span className="text-xs font-medium whitespace-nowrap" data-attr="live-recordings-count">
                    <strong>{humanFriendlyLargeNumber(activeRecordings)}</strong>
                </span>
                <span className="hidden min-[660px]:inline">
                    recently active {pluralize(activeRecordings, 'recording', undefined, false)}
                </span>
            </div>
        </Tooltip>
    )
}
