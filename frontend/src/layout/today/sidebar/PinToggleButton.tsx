import { IconPin, IconPinFilled } from '@posthog/icons'
import { Button, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

/** The pin control after an object's name or on its sidebar row. Every pane's pins look and read the same. */
export function PinToggleButton({
    pinned,
    name,
    busy,
    onToggle,
    size = 'icon-xs',
    dataAttr,
}: {
    pinned: boolean
    name: string
    busy: boolean
    onToggle: () => void
    size?: 'icon' | 'icon-sm' | 'icon-xs'
    dataAttr: string
}): JSX.Element {
    const label = pinned ? 'Unpin from sidebar' : 'Pin to sidebar'
    return (
        <Tooltip>
            <TooltipTrigger
                delay={0}
                render={
                    <Button
                        size={size}
                        aria-label={`${label}: ${name}`}
                        aria-pressed={pinned}
                        disabled={busy}
                        onClick={onToggle}
                        data-attr={dataAttr}
                    />
                }
            >
                {pinned ? <IconPinFilled /> : <IconPin />}
            </TooltipTrigger>
            <TooltipContent>{busy ? 'Updating pinned items' : label}</TooltipContent>
        </Tooltip>
    )
}
