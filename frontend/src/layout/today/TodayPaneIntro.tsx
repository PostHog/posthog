import { useActions, useValues } from 'kea'
import { useId, useRef } from 'react'

import { IconX } from '@posthog/icons'
import { Button, Item, ItemActions, ItemContent, ItemDescription, ItemMedia, ItemTitle } from '@posthog/quill'

import { todayPaneIntroLogic } from './todayPaneIntroLogic'
import { TODAY_PANE_INTROS, TodayIntroPane } from './todayPaneIntros'
import { TODAY_PANES } from './todayRailItems'

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), [tabindex]:not([tabindex="-1"])'

/** Focus would fall to the page body when the intro unmounts, so hand it to the next control in the pane. */
function focusAfter(element: HTMLElement): void {
    const pane = element.closest('aside') ?? document.body
    const next = Array.from(pane.querySelectorAll<HTMLElement>(FOCUSABLE)).find(
        (candidate) =>
            !element.contains(candidate) &&
            element.compareDocumentPosition(candidate) & Node.DOCUMENT_POSITION_FOLLOWING
    )
    next?.focus()
}

/** A short note at the top of a sidebar pane on what the pane is for. Each pane's note is dismissed on its own. */
export function TodayPaneIntro({ pane }: { pane: TodayIntroPane }): JSX.Element | null {
    const { dismissedIntros } = useValues(todayPaneIntroLogic)
    const { dismissIntro } = useActions(todayPaneIntroLogic)
    const ref = useRef<HTMLDivElement>(null)
    const titleId = useId()

    if (dismissedIntros[pane]) {
        return null
    }

    const { title, description } = TODAY_PANE_INTROS[pane]
    const dismissLabel = `Dismiss ${TODAY_PANES[pane].title} intro`

    return (
        <div className="shrink-0 px-2 pb-2">
            <Item
                ref={ref}
                size="xs"
                variant="outline"
                className="flex-nowrap items-start gap-1.5 rounded-md px-2 py-1.5"
                role="note"
                aria-labelledby={titleId}
                data-attr={`today-pane-intro-${pane}`}
            >
                <ItemMedia variant="icon" className="mt-px text-muted-foreground [&_svg]:size-3.5">
                    {TODAY_PANES[pane].icon}
                </ItemMedia>
                <ItemContent className="min-w-0 gap-0.5">
                    <ItemTitle id={titleId} className="text-xs font-medium text-foreground">
                        {title}
                    </ItemTitle>
                    <ItemDescription className="text-xs text-muted-foreground">{description}</ItemDescription>
                </ItemContent>
                <ItemActions>
                    <Button
                        size="icon-xs"
                        className="-me-1 -mt-0.5 text-muted-foreground"
                        aria-label={dismissLabel}
                        tooltip={dismissLabel}
                        data-attr={`today-pane-intro-dismiss-${pane}`}
                        onClick={() => {
                            if (ref.current) {
                                focusAfter(ref.current)
                            }
                            dismissIntro(pane)
                        }}
                    >
                        <IconX />
                    </Button>
                </ItemActions>
            </Item>
        </div>
    )
}
