import { IconBell } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { pluralize } from 'lib/utils/strings'

import { PlatformAlertMute } from './platformAlertFormat'

function muteText(mute: PlatformAlertMute): { label: string; tooltip: string; detail: JSX.Element } {
    switch (mute.kind) {
        case 'snoozed':
            return {
                label: 'Snoozed',
                tooltip: 'Snoozed. Notifications are on hold.',
                detail: (
                    <>
                        <span>until</span>
                        <TZLabel time={mute.until} timestampStyle="absolute" formatDate="MMM D" formatTime="HH:mm" />
                    </>
                ),
            }
        case 'groupsSnoozed': {
            const groups = pluralize(mute.count, 'group')
            return {
                label: `${groups} snoozed`,
                tooltip: `${groups} snoozed. Their notifications are on hold.`,
                detail: <span>{mute.count}</span>,
            }
        }
    }
}

export function PlatformAlertMuteMarker({ mute }: { mute: PlatformAlertMute }): JSX.Element {
    const { label, tooltip, detail } = muteText(mute)
    return (
        <Tooltip title={tooltip}>
            <span
                className="flex items-center gap-1 whitespace-nowrap text-xs text-warning"
                data-attr="platform-alert-mute-marker"
            >
                <span className="relative inline-flex text-base" role="img" aria-label={label}>
                    <IconBell />
                    <span aria-hidden className="absolute inset-0 flex items-center justify-center">
                        <span className="block h-px w-[120%] rotate-45 bg-current" />
                    </span>
                </span>
                {detail}
            </span>
        </Tooltip>
    )
}
