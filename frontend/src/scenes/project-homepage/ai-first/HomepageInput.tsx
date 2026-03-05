import { BindLogic, useActions, useValues } from 'kea'
import { useEffect, useRef, useState } from 'react'

import { IconSearch, IconSparkles } from '@posthog/icons'

import { Search } from 'lib/components/Search/Search'
import { uuid } from 'lib/utils'
import { cn } from 'lib/utils/css-classes'
import { SidebarQuestionInput } from 'scenes/max/components/SidebarQuestionInput'
import { Intro } from 'scenes/max/Intro'
import { maxLogic } from 'scenes/max/maxLogic'
import { MaxThreadLogicProps, maxThreadLogic } from 'scenes/max/maxThreadLogic'

import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'

import { aiFirstHomepageLogic } from './aiFirstHomepageLogic'
import { HOMEPAGE_TAB_ID } from './constants'

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

function IdleInput(): JSX.Element {
    const { query } = useValues(aiFirstHomepageLogic)
    const { setQuery, submitQuery } = useActions(aiFirstHomepageLogic)
    const inputRef = useRef<HTMLInputElement>(null)
    const { text: placeholderText, isVisible: placeholderVisible } = useRotatingPlaceholder(true)

    useEffect(() => {
        inputRef.current?.focus()
    }, [])

    return (
        <label
            htmlFor="homepage-input"
            className="group input-like flex gap-1 items-center relative w-full bg-fill-input border border-primary focus-within:ring-primary py-1 px-2"
        >
            <IconSearch className="size-4 shrink-0 text-tertiary group-focus-within:text-primary" />
            {!query && (
                <span className="text-tertiary pointer-events-none absolute left-8 top-1/2 -translate-y-1/2">
                    <span className="text-tertiary">Ask AI or search </span>
                    <span className="transition-opacity duration-200" style={{ opacity: placeholderVisible ? 1 : 0 }}>
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
    )
}

function HomepageAiInput(): JSX.Element {
    const { threadLogicKey, conversation } = useValues(maxLogic)

    const threadProps: MaxThreadLogicProps = {
        tabId: HOMEPAGE_TAB_ID,
        conversationId: threadLogicKey || uuid(),
        conversation,
    }

    return (
        <BindLogic logic={maxThreadLogic} props={threadProps}>
            <SidebarQuestionInput />
        </BindLogic>
    )
}

export function HomepageInput(): JSX.Element {
    const { mode } = useValues(aiFirstHomepageLogic)

    return (
        <div className="w-full max-w-180 mx-auto py-2">
            {mode === 'idle' && (
                <div className="flex flex-col items-center gap-3">
                    <Intro />
                    <IdleInput />
                </div>
            )}
            {mode === 'ai' && <HomepageAiInput />}
            {mode === 'search' && <Search.Input autoFocus />}
        </div>
    )
}
