import { Menu } from '@base-ui/react/menu'
import { Menubar } from '@base-ui/react/menubar'
import { BindLogic, useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { IconChevronRight, IconLightBulb, IconNotification, IconRocket, IconSearch } from '@posthog/icons'

import { Search } from 'lib/components/Search/Search'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { uuid } from 'lib/utils'
import { SidebarQuestionInput } from 'scenes/max/components/SidebarQuestionInput'
import { Intro } from 'scenes/max/Intro'
import { maxLogic } from 'scenes/max/maxLogic'
import { MaxThreadLogicProps, maxThreadLogic } from 'scenes/max/maxThreadLogic'
import { userLogic } from 'scenes/userLogic'

import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'

import { aiFirstHomepageLogic } from './aiFirstHomepageLogic'
import { HOMEPAGE_TAB_ID } from './constants'

function IdleInput(): JSX.Element {
    const { query, placeholder } = useValues(aiFirstHomepageLogic)
    const { setQuery, submitQuery } = useActions(aiFirstHomepageLogic)
    const inputRef = useRef<HTMLInputElement>(null)

    useEffect(() => {
        const timer = setTimeout(() => inputRef.current?.focus(), 100)
        return () => clearTimeout(timer)
    }, [])

    return (
        <div className="flex flex-col items-center w-full">
            <label
                htmlFor="homepage-input"
                className="group input-like flex gap-1 items-center relative w-full bg-fill-input border border-primary focus-within:ring-primary py-1 px-2"
            >
                <IconSearch className="size-4 shrink-0 text-tertiary group-focus-within:text-primary" />
                {!query && (
                    <span className="text-tertiary pointer-events-none absolute left-8 top-1/2 -translate-y-1/2">
                        <span className="text-tertiary">{placeholder}</span>
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
                    autoComplete="off"
                    className="w-full px-1 py-1 text-sm focus:outline-none border-transparent"
                    autoFocus
                />
            </label>
            <div className="flex flex-col items-center gap-2 w-full">
                <div className="px-4 w-full">
                    <div className="w-full bg-surface-tertiary justify-between rounded-b-lg px-1 pt-0.5 pb-1 font-medium select-none flex items-center gap-1 border-l border-r border-b">
                        <div className="flex items-center gap-0.5">
                            <ButtonPrimitive size="xs" className="text-tertiary" tooltip="Not implemented yet">
                                <KeyboardShortcut forwardslash /> <span className="text-xxs">For commands</span>
                            </ButtonPrimitive>
                            <ButtonPrimitive size="xs" className="text-tertiary" tooltip="Not implemented yet">
                                <KeyboardShortcut atsign /> <span className="text-xxs">Add context</span>
                            </ButtonPrimitive>
                        </div>

                        <div className="flex items-center gap-1">
                            {query.trim() && (
                                <>
                                    <ButtonPrimitive size="xs" className="text-tertiary">
                                        <KeyboardShortcut tab /> <span className="text-xxs">Search</span>
                                    </ButtonPrimitive>
                                    <ButtonPrimitive size="xs" className="text-tertiary">
                                        <KeyboardShortcut enter /> <span className="text-xxs">AI</span>
                                    </ButtonPrimitive>
                                </>
                            )}
                        </div>
                    </div>
                </div>
            </div>
        </div>
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

const LEARN_SUGGESTIONS = [
    'Why did signups drop this week?',
    'Which features do power users love?',
    'Where are users getting stuck in onboarding?',
]

const BUILD_SUGGESTIONS = [
    'Create a dashboard for weekly active users',
    'Set up a funnel from signup to first value moment',
    'Build a cohort of users who churned last month',
]

const SIGNALS_SUGGESTIONS = [
    'What errors are affecting the most users?',
    'How is my latest release performing?',
    'Show me users who activated but never returned',
]

interface SuggestionMenuProps {
    icon: React.ReactNode
    label: string
    suggestions: string[]
    anchor: React.RefObject<HTMLElement | null>
}

function SuggestionMenu({ icon, label, suggestions, anchor }: SuggestionMenuProps): JSX.Element {
    const { setQuery, submitQuery, setHoveredSuggestion } = useActions(aiFirstHomepageLogic)

    return (
        <Menu.Root onOpenChange={(open) => !open && setHoveredSuggestion(null)}>
            <Menu.Trigger
                render={
                    <ButtonPrimitive variant="outline">
                        {icon} {label}
                    </ButtonPrimitive>
                }
            />
            <Menu.Portal>
                <Menu.Positioner className="z-[var(--z-popover)]" sideOffset={4} anchor={anchor} align="center">
                    <Menu.Popup className="primitive-menu-content max-w-96 w-96">
                        <div className="primitive-menu-content-inner flex flex-col gap-px p-1">
                            {suggestions.map((suggestion) => (
                                <Menu.Item
                                    key={suggestion}
                                    onMouseEnter={() => setHoveredSuggestion(suggestion)}
                                    onMouseLeave={() => setHoveredSuggestion(null)}
                                    onClick={() => {
                                        setQuery(suggestion)
                                        submitQuery('ai')
                                    }}
                                    render={
                                        <ButtonPrimitive menuItem className="group">
                                            {suggestion}
                                            <IconChevronRight className="size-4 ml-auto opacity-50 group-hover:opacity-100" />
                                        </ButtonPrimitive>
                                    }
                                />
                            ))}
                        </div>
                    </Menu.Popup>
                </Menu.Positioner>
            </Menu.Portal>
        </Menu.Root>
    )
}

function SuggestionMenubar(): JSX.Element {
    const menubarRef = useRef<HTMLDivElement>(null)

    return (
        <Menubar ref={menubarRef} className="flex gap-2 justify-center">
            <SuggestionMenu
                icon={<IconLightBulb className="size-4" />}
                label="Learn"
                suggestions={LEARN_SUGGESTIONS}
                anchor={menubarRef}
            />
            <SuggestionMenu
                icon={<IconRocket className="size-4" />}
                label="Build"
                suggestions={BUILD_SUGGESTIONS}
                anchor={menubarRef}
            />
            <SuggestionMenu
                icon={<IconNotification className="size-4" />}
                label="Signals"
                suggestions={SIGNALS_SUGGESTIONS}
                anchor={menubarRef}
            />
        </Menubar>
    )
}

export function HomepageInput(): JSX.Element {
    const { mode } = useValues(aiFirstHomepageLogic)
    const { user } = useValues(userLogic)

    return (
        <div className="w-full max-w-180 mx-auto py-2">
            {mode === 'idle' && (
                <div className="flex flex-col items-center gap-3">
                    <Intro forceHeadline={`Hello ${user?.first_name || 'there'}`} forceSubheadline="POSTHOG ONLY" />
                    <IdleInput />
                    <SuggestionMenubar />

                    <p className="w-full flex justify-center text-xs text-tertiary m-0 grow">
                        PostHog AI can make mistakes. Please double-check responses
                    </p>
                </div>
            )}
            {mode === 'ai' && <HomepageAiInput />}
            {mode === 'search' && <Search.Input autoFocus />}
        </div>
    )
}
