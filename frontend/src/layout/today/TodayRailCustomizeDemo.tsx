import { useActions, useValues } from 'kea'
import { useEffect, useRef, useState } from 'react'

import { useReducedMotion } from '@posthog/quill'

import { TodayCursorArt } from './TodayCursorArt'
import { enterTodayCursor, todayCursorRun, useTodayCursorRefs } from './todayCursorDriver'
import { TodayDemoHint } from './TodayDemoHint'
import { todayDesignChangelogLogic } from './todayDesignChangelogLogic'
import { todayRailLayoutLogic } from './todayRailLayoutLogic'
import { TodayTourPoint, centerOf } from './todayTourGeometry'

const HOME_TILE = '[data-attr="today-rail-home"]'
const AI_BUTTON = '[data-attr="today-top-bar-side-panel"]'
const MORE_TILE = '[data-attr="help-menu-button"]'
const CUSTOMIZE_ITEM = '[data-attr="today-rail-customize"]'

// Lets the menu or dialog a click opened render before the cursor looks for the next target.
const SETTLE_MS = 350
// Chats sat right under Home, so the first step points at that gap.
const CHATS_SLOT_BELOW_HOME_PX = 28
// How long the PostHog AI panel stays open before the cursor closes it again.
const AI_PANEL_SHOWN_MS = 1600
// How long the More menu stays open before the cursor moves on, so a person can see what is in it.
const MORE_MENU_SHOWN_MS = 1000
// The cursor rests on its target this long before it clicks, so the click reads as a choice.
const REST_BEFORE_CLICK_MS = 400

/** A click the cursor makes: where, what the click does, and how long the cursor waits around it. */
interface DemoClick {
    target: string
    press: (element: HTMLElement) => void
    restMs?: number
    holdMs: number
}

function pointAnchor(point: TodayTourPoint): { getBoundingClientRect: () => DOMRect } {
    return { getBoundingClientRect: () => new DOMRect(point.x, point.y, 0, 0) }
}

/**
 * The tour's pretend cursor, showing where chats went and where the rail is arranged: it points where Chats was,
 * opens and closes the PostHog AI panel, then clicks More and Customize navigation. The cursor is decoration only, so
 * it ignores the pointer and is hidden from assistive tech.
 */
export function TodayRailCustomizeDemo(): JSX.Element | null {
    const { demo } = useValues(todayDesignChangelogLogic)
    const { endDemo, setCustomizeHint } = useActions(todayDesignChangelogLogic)
    const { setMoreMenuOpen, setCustomizeOpen } = useActions(todayRailLayoutLogic)
    const reducedMotion = useReducedMotion()
    const refs = useTodayCursorRefs(demo?.origin ?? { x: 0, y: 0 })
    // Where the card for the first step points: the rail's edge, beside the gap Chats left.
    const [hintPoint, setHintPoint] = useState<TodayTourPoint | null>(null)
    // Resolves the wait on the first card's Next button.
    const nextRef = useRef<(() => void) | null>(null)

    useEffect(() => {
        if (!demo) {
            return
        }
        enterTodayCursor(refs, demo.origin, reducedMotion)
        const controller = new AbortController()
        const { sleep, findElement, moveTo, click } = todayCursorRun(controller.signal, reducedMotion, refs)
        const openCustomize = (): void => {
            setMoreMenuOpen(false)
            setCustomizeOpen(true)
        }
        const waitForNext = (): Promise<void> =>
            new Promise((resolve, reject) => {
                nextRef.current = resolve
                controller.signal.addEventListener('abort', () => reject(controller.signal.reason), { once: true })
            })

        const explainChats = async (): Promise<void> => {
            const home = await findElement(HOME_TILE)
            if (!home) {
                return
            }
            const rect = home.getBoundingClientRect()
            const slot = { x: rect.left + rect.width / 2, y: rect.bottom + CHATS_SLOT_BELOW_HOME_PX }
            await moveTo(slot)
            // The card opens past the rail's edge, so it covers neither the cursor nor the rail.
            setHintPoint({ x: home.closest('nav')?.getBoundingClientRect().right ?? rect.right, y: slot.y })
            await waitForNext()
            setHintPoint(null)
        }

        // Real clicks on the PostHog AI button, so its panel opens and closes the way it does for the person.
        const clicks: DemoClick[] = [
            { target: AI_BUTTON, press: (button) => button.click(), holdMs: AI_PANEL_SHOWN_MS },
            { target: AI_BUTTON, press: (button) => button.click(), holdMs: SETTLE_MS },
            { target: MORE_TILE, press: () => setMoreMenuOpen(true), holdMs: MORE_MENU_SHOWN_MS },
            { target: CUSTOMIZE_ITEM, press: openCustomize, restMs: REST_BEFORE_CLICK_MS, holdMs: SETTLE_MS },
        ]

        const run = async (): Promise<void> => {
            if (demo.explainChats) {
                await explainChats()
            }
            for (const step of clicks) {
                const element = await findElement(step.target)
                if (!element) {
                    continue
                }
                await moveTo(centerOf(element))
                await sleep(step.restMs ?? 0)
                await click(() => step.press(element))
                await sleep(step.holdMs)
            }
            // Ends in the dialog even when a target was missing on the way.
            openCustomize()
            setCustomizeHint(true)
            endDemo()
        }

        run().catch((error: unknown) => {
            // An abort is the demo ending early. Anything else would leave the cursor stuck on screen.
            if (!controller.signal.aborted) {
                endDemo()
                throw error
            }
        })
        return () => {
            controller.abort()
            nextRef.current = null
        }
    }, [demo, reducedMotion, refs, setMoreMenuOpen, setCustomizeOpen, setCustomizeHint, endDemo])

    return (
        <>
            {demo && <TodayCursorArt refs={refs} />}
            {hintPoint && (
                <TodayDemoHint
                    anchor={pointAnchor(hintPoint)}
                    side="right"
                    align="center"
                    title="Chats is hidden by default now"
                    description="Your chats are in PostHog AI, and you can put Chats back on the rail. Here's how."
                    actionLabel="Next"
                    onAction={() => nextRef.current?.()}
                    onDismiss={() => {
                        setHintPoint(null)
                        endDemo()
                    }}
                />
            )}
        </>
    )
}
