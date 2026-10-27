// PROTOTYPE — throwaway. Floating bar to flip between UI prototype variants via `?variant=`.
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect } from 'react'

import { IconChevronLeft, IconChevronRight } from '@posthog/icons'

export interface PrototypeVariant {
    key: string
    name: string
}

export interface PrototypeExtraParam {
    param: string
    label: string
    options: string[]
}

function isTyping(): boolean {
    const el = document.activeElement as HTMLElement | null
    return !!el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.isContentEditable)
}

export function usePrototypeParam(param: string, fallback: string): string {
    const { searchParams } = useValues(router)
    const value = searchParams[param]
    return typeof value === 'string' && value ? value : fallback
}

export function PrototypeSwitcher({
    variants,
    extra = [],
}: {
    variants: PrototypeVariant[]
    extra?: PrototypeExtraParam[]
}): JSX.Element | null {
    const { searchParams, location } = useValues(router)
    const { replace } = useActions(router)
    const current = usePrototypeParam('variant', variants[0].key)
    const index = Math.max(
        0,
        variants.findIndex((v) => v.key === current)
    )

    const setParam = (param: string, value: string): void => {
        replace(location.pathname, { ...searchParams, [param]: value }, location.hash)
    }
    const cycle = (delta: number): void => {
        setParam('variant', variants[(index + delta + variants.length) % variants.length].key)
    }

    useEffect(() => {
        const onKey = (e: KeyboardEvent): void => {
            if (isTyping() || e.metaKey || e.ctrlKey || e.altKey) {
                return
            }
            if (e.key === 'ArrowLeft') {
                cycle(-1)
            } else if (e.key === 'ArrowRight') {
                cycle(1)
            }
        }
        window.addEventListener('keydown', onKey)
        return () => window.removeEventListener('keydown', onKey)
    })

    if (process.env.NODE_ENV === 'production') {
        return null
    }

    return (
        <div className="fixed bottom-4 left-1/2 -translate-x-1/2 z-[9999] flex items-center gap-2 rounded-full bg-black text-white px-2 py-1.5 shadow-xl text-xs font-medium">
            <span className="px-2 py-0.5 rounded-full bg-[#f54e00] text-[10px] uppercase tracking-wide">Prototype</span>
            <button className="p-1 rounded-full hover:bg-white/20 cursor-pointer" onClick={() => cycle(-1)}>
                <IconChevronLeft />
            </button>
            <span className="min-w-56 text-center">
                {variants[index].key} — {variants[index].name}
            </span>
            <button className="p-1 rounded-full hover:bg-white/20 cursor-pointer" onClick={() => cycle(1)}>
                <IconChevronRight />
            </button>
            {extra.map(({ param, label, options }) => {
                const value = searchParams[param] ?? options[0]
                return (
                    <span key={param} className="flex items-center gap-1 border-l border-white/30 pl-2 ml-1">
                        <span className="opacity-60">{label}</span>
                        {options.map((option) => (
                            <button
                                key={option}
                                onClick={() => setParam(param, option)}
                                className={`px-2 py-0.5 rounded-full cursor-pointer ${
                                    value === option ? 'bg-white text-black' : 'hover:bg-white/20'
                                }`}
                            >
                                {option}
                            </button>
                        ))}
                    </span>
                )
            })}
        </div>
    )
}
