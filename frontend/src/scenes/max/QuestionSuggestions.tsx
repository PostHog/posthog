import './QuestionSuggestions.scss'

import { IconBook, IconGear, IconGraph, IconHogQL, IconPlug, IconRewindPlay } from '@posthog/icons'
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
    label: string
    icon: JSX.Element
    suggestions: SuggestionItem[]
    url?: string
    tooltip?: string
}

// Export the data and type it with SuggestionGroup
export const QUESTION_SUGGESTIONS_DATA: SuggestionGroup[] = [
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
            },
            {
                label: 'What are the most popular pages or screens?',
            },
            {
                label: 'What is the retention in the last two weeks?',
            },
            {
                label: 'What are the top referring domains?',
            },
            {
                label: 'Calculate a conversion rate for <events or features>',
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
                label: 'Explain autocapture',
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
                label: 'How can I set up the session replay in <a framework or language>',
                content: 'How can I set up the session replay in ',
            },
            {
                label: 'How can I set up the feature flags in...',
                content: 'How can I set up the feature flags in ',
            },
            {
                label: 'How can I set up the experiments in...',
                content: 'How can I set up the experiments in ',
            },
            {
                label: 'How can I set up the data warehouse in...',
                content: 'How can I set up the data warehouse in ',
            },
            {
                label: 'How can I set up the error tracking in...',
                content: 'How can I set up the error tracking in ',
            },
            {
                label: 'How can I set up the LLM Observability in...',
                content: 'How can I set up the LLM Observability in',
            },
            {
                label: 'How can I set up the product analytics in...',
                content: 'How can I set up the product analytics in',
            },
        ],
        tooltip: 'Max can help you set up PostHog SDKs in your stack.',
    },
    {
        label: 'Session Replay',
        icon: <IconRewindPlay />,
        suggestions: [
            {
                label: 'Find recordings for <description>',
                content: 'Find recordings for ',
            },
        ],
        url: productUrls.replay(),
        tooltip: 'Max can find session recordings for you.',
    },
] as const

export function QuestionSuggestions(): JSX.Element {
    const suggestionListRef = useRef<HTMLUListElement | null>(null)

    const { dataProcessingAccepted } = useValues(maxLogic)
    const { askMax, setQuestion, focusInput } = useActions(maxLogic)
    const { openSettingsPanel } = useActions(sidePanelSettingsLogic)

    const logic = useMountedLogic(questionSuggestionsLogic)
    const { activeSuggestionGroup } = useValues(logic)
    const { setActiveSuggestionGroupLabel } = useActions(logic)

    useClickOutside([suggestionListRef], () => {
        if (activeSuggestionGroup) {
            setActiveSuggestionGroupLabel(null)
        }
    })

    return (
        <div className="flex flex-col items-center justify-center w-[min(48rem,100%)] gap-y-2">
            <h3 className="text-center text-xs font-medium mb-0 text-secondary">
                {activeSuggestionGroup ? activeSuggestionGroup.label : 'Ask Max about'}
            </h3>
            {!activeSuggestionGroup ? (
                <ul className="flex items-center justify-center flex-wrap gap-x-2 gap-y-1.5">
                    {QUESTION_SUGGESTIONS_DATA.map((group) => (
                        <li key={group.label} className="shrink">
                            <LemonButton
                                onClick={() => {
                                    // If it's a product-based skill, open the URL first
                                    if (group.url && !router.values.currentLocation.pathname.includes(group.url)) {
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
            ) : (
                <ul className="flex flex-col gap-y-1.5" ref={suggestionListRef}>
                    {activeSuggestionGroup.suggestions.map((suggestion, index) => (
                        <li
                            key={suggestion.label}
                            className="QuestionSuggestion"
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{ '--index': index } as React.CSSProperties}
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
                                className="text-left [&_span]:line-clamp-1"
                            >
                                {suggestion.label}
                            </LemonButton>
                        </li>
                    ))}
                </ul>
            )}
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
