import { useState } from 'react'

import { IconInfo } from '@posthog/icons'
import { Button, Popover, PopoverContent, PopoverTrigger, Text } from '@posthog/quill'

import { TODAY_PANE_INTROS } from './todayPaneIntros'
import { TODAY_PANES } from './todayRailItems'
import type { TodayRailPane } from './todayShellLogic'

/** An info button in the pane header. Its popover says what the pane is for. */
export function TodayPaneIntro({ pane }: { pane: TodayRailPane }): JSX.Element {
    const [open, setOpen] = useState(false)
    const { title, description } = TODAY_PANE_INTROS[pane]
    const label = `About ${TODAY_PANES[pane].title}`

    return (
        <Popover open={open} onOpenChange={setOpen}>
            <PopoverTrigger
                render={
                    <Button
                        size="icon"
                        className="text-muted-foreground"
                        aria-label={label}
                        tooltip={open ? undefined : label}
                        data-attr={`today-pane-intro-${pane}`}
                    />
                }
            >
                <IconInfo />
            </PopoverTrigger>
            <PopoverContent side="bottom" align="end" arrow className="max-w-72">
                <div className="flex flex-col gap-1">
                    <Text size="sm" weight="semibold" render={<h3 />} className="m-0">
                        {title}
                    </Text>
                    <Text size="xs" variant="muted" className="m-0">
                        {description}
                    </Text>
                </div>
            </PopoverContent>
        </Popover>
    )
}
