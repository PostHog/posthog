import { IconBell } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import { PlatformAlertMute } from './platformAlertFormat'

export function PlatformAlertMuteMarker({ mute }: { mute: PlatformAlertMute }): JSX.Element {
    const groups = mute.until === null ? (mute.count === 1 ? '1 group' : `${mute.count} groups`) : null
    return (
        <Tooltip
            title={groups ? `${groups} snoozed. Notifications are on hold.` : 'Snoozed. Notifications are on hold.'}
        >
            <span
                className="flex items-center gap-1 whitespace-nowrap text-xs text-warning"
                data-attr="platform-alert-mute-marker"
            >
                <span className="relative inline-flex text-base">
                    <IconBell />
                    <span aria-hidden className="absolute inset-0 flex items-center justify-center">
                        <span className="block h-px w-[120%] rotate-45 bg-current" />
                    </span>
                </span>
                {mute.until === null ? (
                    <span>{mute.count}</span>
                ) : (
                    <>
                        <span>until</span>
                        <TZLabel time={mute.until} timestampStyle="absolute" formatDate="MMM D" formatTime="HH:mm" />
                    </>
                )}
            </span>
        </Tooltip>
    )
}
