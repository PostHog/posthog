import './QuestionSuggestions.scss'

import { IconBook, IconChevronLeft, IconGear, IconGraph, IconHogQL, IconPlug, IconRewindPlay } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import { useActions, useMountedLogic, useValues } from 'kea'
import { router } from 'kea-router'
import { MutableRefObject } from 'react'
import { useRef } from 'react'
import { useEffect } from 'react'
import { urls } from 'scenes/urls'

import { sidePanelSettingsLogic } from '~/layout/navigation-3000/sidepanel/panels/sidePanelSettingsLogic'
import { productUrls } from '~/products'

import { maxLogic } from './maxLogic'
import { questionSuggestionsLogic } from './questionSuggestionsLogic'

// Define and export SuggestionGroup type
export interface SuggestionItem {
    label: string
    // In case the actual question to Max is different from the label
    content?: string
}
export interface SuggestionGroup {
    readonly label: string
    readonly icon: JSX.Element
    readonly suggestions: readonly SuggestionItem[]
    readonly url?: string
    readonly tooltip?: string
}

// Export the data and type it with SuggestionGroup
export const QUESTION_SUGGESTIONS_DATA: readonly SuggestionGroup[] = [
    {
        label: 'SQL',
        icon: <IconHogQL />,
        suggestions: [
            {
                label: 'Generate an SQL query to',
                content: 'Generate an SQL query to ',
            },
        ],
        url: urls.sqlEditor(),
        tooltip: 'Max can generate SQL queries using your PostHog data and the data warehouse.',
    },
    {
        label: 'Product Analytics',
        icon: <IconGraph />,
        suggestions: [
            {
                label: 'Create a funnel of the Pirate Metrics (AARRR)',
                content: 'Create a funnel of the Pirate Metrics (AARRR)',
            },
            {
                label: 'What are the most popular pages or screens?',
                content: 'What are the most popular pages or screens?',
            },
            {
                label: 'What is the retention in the last two weeks?',
                content: 'What is the retention in the last two weeks?',
            },
            {
                label: 'What are the top referring domains?',
                content: 'What are the top referring domains?',
            },
            {
                label: 'Calculate a conversion rate for <a feature or events>',
                content: 'Calculate a conversion rate for ',
            },
        ],
        tooltip: 'Max can generate insights from natural language and tweak existing ones.',
    },
    {
        label: 'Docs',
        icon: <IconBook />,
        suggestions: [
            {
                label: 'How can I create a feature flag?',
            },
            {
                label: 'Where do I watch session replays?',
            },
            {
                label: 'Help me set up an experiment',
            },
            {
                label: 'What is the autocapture?',
            },
            {
                label: 'How can I capture an exception?',
            },
        ],
        tooltip: 'Max can help you find the right documentation pieces.',
    },
    {
        label: 'Set up',
        icon: <IconPlug />,
        suggestions: [
            {
                label: 'How can I set up session replay in <a framework or language>',
                content: 'How can I set up session replay in ',
            },
            {
                label: 'How can I set up feature flags in...',
                content: 'How can I set up feature flags in ',
            },
            {
                label: 'How can I set up experiments in...',
                content: 'How can I set up experiments in ',
            },
            {
                label: 'How can I set up data warehouse in...',
                content: 'How can I set up data warehouse in ',
            },
            {
                label: 'How can I set up error tracking in...',
                content: 'How can I set up error tracking in ',
            },
            {
                label: 'How can I set up LLM Observability in...',
                content: 'How can I set up LLM Observability in',
            },
            {
                label: 'How can I set up product analytics in...',
                content: 'How can I set up product analytics in',
            },
        ],
        tooltip: 'Max can help you set up PostHog SDKs in your stack.',
    },
    {
        label: 'Session Replay',
        icon: <IconRewindPlay />,
        suggestions: [
            {
                label: 'Find recordings <description>',
                content: 'Find recordings ',
            },
        ],
        url: productUrls.replay(),
        tooltip: 'Max can find session recordings for you.',
    },
] as const // as const is good for type inference, but SuggestionGroup[] ensures structure

export function QuestionSuggestions(): JSX.Element {
    const suggestionListRef = useRef<HTMLDivElement | null>(null)

    const { dataProcessingAccepted } = useValues(maxLogic)
    const { askMax, setQuestion, focusInput } = useActions(maxLogic) // Changed submit to askMax
    const { openSettingsPanel } = useActions(sidePanelSettingsLogic)

    const logic = useMountedLogic(questionSuggestionsLogic)
    const { activeSuggestionGroup } = useValues(logic)
    const { setActiveSuggestionGroupLabel } = useActions(logic)

    // Key for re-rendering suggestion list to help reset animations
    const suggestionListKey = activeSuggestionGroup ? activeSuggestionGroup.label : 'categories'

    useClickOutside([suggestionListRef], () => {
        if (activeSuggestionGroup) {
            setActiveSuggestionGroupLabel(null)
        }
    })

    return (
        <div className="flex flex-col items-center justify-center w-[min(48rem,100%)] gap-y-2">
            <h3 className="w-full text-center text-xs font-medium mb-0 text-secondary">Ask Max about</h3>
            <div ref={suggestionListRef}>
                {!activeSuggestionGroup ? (
                    <>
                        <ul className="flex items-center justify-center flex-wrap gap-x-2 gap-y-1.5">
                            {QUESTION_SUGGESTIONS_DATA.map((group) => (
                                <li key={group.label} className="shrink">
                                    <LemonButton
                                        onClick={() => {
                                            // If it's a product-based skill, open the URL first
                                            if (
                                                group.url &&
                                                !router.values.currentLocation.pathname.includes(group.url)
                                            ) {
                                                router.actions.push(group.url)
                                            }

                                            // If there's only one suggestion, we can just ask Max directly
                                            if (group.suggestions.length <= 1) {
                                                if (group.suggestions[0].content) {
                                                    // Content requires to write something to continue
                                                    setQuestion(group.suggestions[0].content)
                                                    focusInput()
                                                } else {
                                                    // Otherwise, just launch the generation
                                                    askMax(group.suggestions[0].label)
                                                }
                                            } else {
                                                setActiveSuggestionGroupLabel(group.label)
                                            }
                                        }}
                                        size="xsmall"
                                        type="secondary"
                                        icon={group.icon}
                                        center
                                        disabledReason={
                                            !dataProcessingAccepted ? 'Please accept OpenAI processing data' : undefined
                                        }
                                        tooltip={group.tooltip}
                                    >
                                        {group.label}
                                    </LemonButton>
                                </li>
                            ))}
                            <li>
                                <LemonButton
                                    onClick={() =>
                                        openSettingsPanel({ sectionId: 'environment-max', settingId: 'core-memory' })
                                    }
                                    size="xsmall"
                                    type="secondary"
                                    icon={<IconGear />}
                                    tooltip="Edit Max's memory"
                                />
                            </li>
                        </ul>
                    </>
                ) : (
                    <div className="w-full flex flex-col items-center gap-y-2" key={suggestionListKey}>
                        <div className="flex items-center justify-between w-full px-1 sm:px-2">
                            <LemonButton
                                icon={<IconChevronLeft />}
                                onClick={() => setActiveSuggestionGroupLabel(null)}
                                size="small"
                                type="tertiary"
                            >
                                Back
                            </LemonButton>
                            <h3 className="text-sm font-medium mb-0 text-primary text-center flex-1 truncate px-1">
                                {activeSuggestionGroup.label}
                            </h3>
                            <div className="text-right min-w-[60px]">
                                {' '}
                                {/* Replaced inline style with Tailwind class */}
                                {activeSuggestionGroup.url && (
                                    <LemonButton
                                        size="small"
                                        type="secondary"
                                        to={activeSuggestionGroup.url}
                                        targetBlank
                                    >
                                        Go to {activeSuggestionGroup.label}
                                    </LemonButton>
                                )}
                            </div>
                        </div>

                        <div className="flex flex-col gap-y-1.5 w-full items-stretch max-h-[200px] overflow-y-auto px-2">
                            {activeSuggestionGroup.suggestions.map((suggestion, index) => (
                                <div
                                    key={suggestion.label}
                                    className={`QuestionSuggestion fill-forwards delay-[${index * 40}ms]`}
                                >
                                    <LemonButton
                                        fullWidth
                                        onClick={() => {
                                            if (suggestion.content) {
                                                // Content requires to write something to continue
                                                setQuestion(suggestion.content)
                                                focusInput()
                                            } else {
                                                // Otherwise, just launch the generation
                                                askMax(suggestion.label)
                                            }

                                            // Close suggestions after asking
                                            setActiveSuggestionGroupLabel(null)
                                        }}
                                        size="small"
                                        type="tertiary"
                                        disabledReason={
                                            !dataProcessingAccepted ? 'Please accept OpenAI processing data' : undefined
                                        }
                                        title={suggestion.label}
                                        className="justify-start text-left truncate"
                                    >
                                        <span className="truncate">{suggestion.label}</span>
                                    </LemonButton>
                                </div>
                            ))}
                        </div>
                    </div>
                )}
            </div>
        </div>
    )
}

function useClickOutside<T extends HTMLElement>(
    elementRefs: MutableRefObject<T | null>[],
    callback: (event: MouseEvent) => void
): void {
    const callbackRef = useRef(callback)
    callbackRef.current = callback
    useEffect(() => {
        const handleClickOutside = (event: MouseEvent): void => {
            const target = event.target
            if (!(target instanceof Node) || elementRefs.every((elementRef) => !elementRef.current?.contains(target))) {
                callbackRef.current?.(event)
            }
        }
        document.addEventListener('click', handleClickOutside, true)
        return () => document.removeEventListener('click', handleClickOutside, true)
    }, [elementRefs])
}
