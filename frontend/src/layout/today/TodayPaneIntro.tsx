import { useActions, useValues } from 'kea'
import { MouseEvent, useId, useState } from 'react'

import { IconInfo, IconX } from '@posthog/icons'
import { Button, Item, ItemActions, ItemContent, ItemDescription, ItemMedia, ItemTitle, cn } from '@posthog/quill'

import { todayPaneIntroLogic } from './todayPaneIntroLogic'
import { TODAY_PANE_INTROS } from './todayPaneIntros'
import { TODAY_PANES } from './todayRailItems'
import type { TodayRailPane } from './todayShellLogic'

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), [tabindex]:not([tabindex="-1"])'

/** The X unmounts with the intro, so a keyboard dismissal hands focus to the next visible control in the pane. */
function focusNextAfter(button: HTMLElement): void {
    const pane = button.closest('aside') ?? document.body
    const next = Array.from(pane.querySelectorAll<HTMLElement>(FOCUSABLE)).find(
        (candidate) =>
            button.compareDocumentPosition(candidate) & Node.DOCUMENT_POSITION_FOLLOWING && candidate.checkVisibility()
    )
    next?.focus()
}

export function TodayPaneIntro({ pane }: { pane: TodayRailPane }): JSX.Element | null {
    const { isIntroShown } = useValues(todayPaneIntroLogic)
    const { dismissIntro } = useActions(todayPaneIntroLogic)
    // `closing` keeps the intro on screen for its exit animation after the dismissal is already saved.
    const [closing, setClosing] = useState(false)
    const [closed, setClosed] = useState(false)
    const titleId = useId()

    // Home opens no sidebar, so it has no intro.
    if (pane === 'home' || closed || (!closing && !isIntroShown(pane))) {
        return null
    }

    const { title, description } = TODAY_PANE_INTROS[pane]
    const dismissLabel = `Dismiss ${TODAY_PANES[pane].title} intro`

    const onDismiss = (event: MouseEvent<HTMLButtonElement>): void => {
        if (closing) {
            return
        }
        // A click with no pointer behind it came from the keyboard or a screen reader. It skips the animation, and
        // focus moves on. A pointer dismissal leaves focus alone, so a tap never opens the keyboard for the search.
        const fromKeyboard = event.detail === 0
        if (fromKeyboard) {
            focusNextAfter(event.currentTarget)
        } else if (!window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
            setClosing(true)
        }
        dismissIntro(pane)
    }

    return (
        // The row collapses to zero height, so the pane below slides up into the space instead of jumping.
        <div
            className={cn(
                'grid shrink-0 transition-[grid-template-rows] duration-200 ease-out motion-reduce:transition-none',
                closing ? 'grid-rows-[0fr]' : 'grid-rows-[1fr]'
            )}
            {...(closing ? { inert: '' } : {})}
            onTransitionEnd={(event) => {
                if (closing && event.target === event.currentTarget) {
                    setClosed(true)
                }
            }}
        >
            <div className="min-h-0 overflow-hidden px-2 pb-2">
                <Item
                    size="xs"
                    variant="outline"
                    className={cn(
                        'flex-nowrap transition-[opacity,scale] duration-150 ease-out motion-reduce:transition-none',
                        closing && 'scale-[0.98] opacity-0'
                    )}
                    role="note"
                    aria-labelledby={titleId}
                    data-attr={`today-pane-intro-${pane}`}
                >
                    <ItemMedia variant="icon" aria-hidden>
                        <IconInfo />
                    </ItemMedia>
                    <ItemContent className="min-w-0">
                        <ItemTitle id={titleId}>{title}</ItemTitle>
                        <ItemDescription className="line-clamp-none">{description}</ItemDescription>
                    </ItemContent>
                    <ItemActions className="self-start">
                        <Button
                            variant="link-muted"
                            size="icon-xs"
                            aria-label={dismissLabel}
                            tooltip={dismissLabel}
                            data-attr={`today-pane-intro-dismiss-${pane}`}
                            onClick={onDismiss}
                        >
                            <IconX />
                        </Button>
                    </ItemActions>
                </Item>
            </div>
        </div>
    )
}
