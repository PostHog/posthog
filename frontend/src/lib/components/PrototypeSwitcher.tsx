/**
 * PROTOTYPE TOOLING — floating variant switcher for throwaway UI prototypes.
 * Renders nothing in production builds. Delete together with the prototype it serves.
 */
import { useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect } from 'react'

import { IconChevronLeft, IconChevronRight } from '@posthog/icons'

export interface PrototypeVariant {
    key: string
    name: string
}

interface PrototypeSwitcherProps {
    variants: PrototypeVariant[]
    current: string
    /** Extra live-state readout shown in the bar, e.g. the prototype's current selection. */
    stateLabel?: string
}

export function PrototypeSwitcher(props: PrototypeSwitcherProps): JSX.Element | null {
    if (process.env.NODE_ENV !== 'development') {
        return null
    }
    return <PrototypeSwitcherBar {...props} />
}

function PrototypeSwitcherBar({ variants, current, stateLabel }: PrototypeSwitcherProps): JSX.Element {
    const { location, searchParams, hashParams } = useValues(router)

    const cycle = (delta: number): void => {
        const index = Math.max(
            0,
            variants.findIndex((v) => v.key === current)
        )
        const next = variants[(index + delta + variants.length) % variants.length]
        router.actions.replace(location.pathname, { ...searchParams, variant: next.key }, hashParams)
    }

    useEffect(() => {
        const onKeyDown = (e: KeyboardEvent): void => {
            const target = e.target as HTMLElement | null
            if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable)) {
                return
            }
            if (e.key === 'ArrowLeft') {
                cycle(-1)
            } else if (e.key === 'ArrowRight') {
                cycle(1)
            }
        }
        window.addEventListener('keydown', onKeyDown)
        return () => window.removeEventListener('keydown', onKeyDown)
    })

    const currentVariant = variants.find((v) => v.key === current)

    return (
        <div className="fixed bottom-4 left-1/2 z-[10000] flex -translate-x-1/2 items-center gap-1 rounded-full bg-black/90 px-2 py-1 text-white shadow-xl">
            <button
                type="button"
                className="flex cursor-pointer items-center rounded-full p-1 hover:bg-white/20"
                onClick={() => cycle(-1)}
                aria-label="Previous variant"
            >
                <IconChevronLeft />
            </button>
            <span className="select-none whitespace-nowrap px-1 text-xs font-semibold">
                PROTOTYPE {current}
                {currentVariant ? ` — ${currentVariant.name}` : ''}
                {stateLabel ? <span className="ml-2 font-normal opacity-70">{stateLabel}</span> : null}
            </span>
            <button
                type="button"
                className="flex cursor-pointer items-center rounded-full p-1 hover:bg-white/20"
                onClick={() => cycle(1)}
                aria-label="Next variant"
            >
                <IconChevronRight />
            </button>
        </div>
    )
}
