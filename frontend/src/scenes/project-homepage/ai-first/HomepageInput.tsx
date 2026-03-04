import { useActions, useValues } from 'kea'
import { useEffect, useRef, useState } from 'react'

import { IconSearch, IconSparkles } from '@posthog/icons'

import { cn } from 'lib/utils/css-classes'

import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'

import { aiFirstHomepageLogic } from './aiFirstHomepageLogic'

const PLACEHOLDER_OPTIONS = [
    'insights...',
    'dashboards...',
    'feature flags...',
    'experiments...',
    'surveys...',
    'notebooks...',
    'cohorts...',
    'persons...',
    'recordings filters...',
]

const PLACEHOLDER_CYCLE_INTERVAL = 3000

function useRotatingPlaceholder(isActive: boolean): { text: string; isVisible: boolean } {
    const [index, setIndex] = useState(0)
    const [isVisible, setIsVisible] = useState(true)

    useEffect(() => {
        if (!isActive) {
            setIndex(0)
            setIsVisible(true)
            return
        }

        let timeoutId: ReturnType<typeof setTimeout> | undefined

        const interval = setInterval(() => {
            setIsVisible(false)
            timeoutId = setTimeout(() => {
                setIndex((prev) => (prev + 1) % PLACEHOLDER_OPTIONS.length)
                setIsVisible(true)
            }, 200)
        }, PLACEHOLDER_CYCLE_INTERVAL)

        return () => {
            clearInterval(interval)
            if (timeoutId !== undefined) {
                clearTimeout(timeoutId)
            }
        }
    }, [isActive])

    return { text: PLACEHOLDER_OPTIONS[index], isVisible }
}

export function HomepageInput(): JSX.Element {
    const { query, mode } = useValues(aiFirstHomepageLogic)
    const { setQuery, submitQuery } = useActions(aiFirstHomepageLogic)
    const inputRef = useRef<HTMLInputElement>(null)
    const { text: placeholderText, isVisible: placeholderVisible } = useRotatingPlaceholder(mode === 'idle')

    useEffect(() => {
        if (mode === 'idle') {
            inputRef.current?.focus()
        }
    }, [mode])

    return (
        <div className="w-full max-w-[640px] mx-auto px-4">
            <label
                htmlFor="homepage-input"
                className="group input-like flex gap-1 items-center relative w-full bg-fill-input border border-primary focus-within:ring-primary py-1 px-2"
            >
                <IconSearch className="size-4 shrink-0 text-tertiary group-focus-within:text-primary" />
                {!query && (
                    <span className="text-tertiary pointer-events-none absolute left-8 top-1/2 -translate-y-1/2">
                        <span className="text-tertiary">Ask AI or search </span>
                        <span
                            className="transition-opacity duration-200"
                            style={{ opacity: placeholderVisible ? 1 : 0 }}
                        >
                            {placeholderText}
                        </span>
                    </span>
                )}
                <input
                    ref={inputRef}
                    id="homepage-input"
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    onKeyDown={(e) => {
                        if (e.key === 'Enter' && query.trim()) {
                            e.preventDefault()
                            submitQuery('ai')
                        }
                        if (e.key === 'Tab' && query.trim()) {
                            e.preventDefault()
                            submitQuery('search')
                        }
                    }}
                    className="w-full px-1 py-1 text-sm focus:outline-none border-transparent"
                    autoFocus
                />
                {query.trim() && (
                    <div className="flex items-center gap-2 shrink-0">
                        <span
                            className={cn(
                                'text-xs text-tertiary whitespace-nowrap flex items-center gap-1',
                                'hover:text-ai'
                            )}
                        >
                            <IconSparkles className="size-3.5" />
                            <KeyboardShortcut enter /> AI
                        </span>
                        <span className="text-xs text-tertiary whitespace-nowrap flex items-center gap-1">
                            <KeyboardShortcut tab /> Search
                        </span>
                    </div>
                )}
            </label>
        </div>
    )
}
