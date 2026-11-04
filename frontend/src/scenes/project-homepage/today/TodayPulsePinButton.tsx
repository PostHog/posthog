import { IconPin, IconPinFilled } from '@posthog/icons'
import { Button } from '@posthog/quill'

export function TodayPulsePinButton({
    pinned,
    disabledReason,
    onToggle,
}: {
    pinned: boolean
    disabledReason?: string
    onToggle: () => void
}): JSX.Element {
    const label = pinned ? 'Unpin from your home' : 'Pin to your home'
    return (
        <Button
            size="icon-xs"
            aria-label={label}
            tooltip={label}
            aria-pressed={pinned}
            disabledReason={disabledReason}
            onClick={onToggle}
            className={pinned ? undefined : 'text-muted-foreground'}
            data-attr="today-pulse-card-pin"
        >
            {pinned ? <IconPinFilled /> : <IconPin />}
        </Button>
    )
}
