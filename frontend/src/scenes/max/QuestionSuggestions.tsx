import './QuestionSuggestions.scss'

import { IconGear } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import { useActions, useMountedLogic, useValues } from 'kea'
import { router } from 'kea-router'
import { MutableRefObject } from 'react'
import { useRef } from 'react'
import { useEffect } from 'react'

import { sidePanelSettingsLogic } from '~/layout/navigation-3000/sidepanel/panels/sidePanelSettingsLogic'

import { maxLogic } from './maxLogic'
import { maxQuestionSuggestionsLogic } from './maxQuestionSuggestionsLogic'

export function QuestionSuggestions(): JSX.Element {
    const suggestionListRef = useRef<HTMLUListElement | null>(null)

    const { dataProcessingAccepted } = useValues(maxLogic)
    const { askMax, setQuestion, focusInput } = useActions(maxLogic)
    const { openSettingsPanel } = useActions(sidePanelSettingsLogic)

    const logic = useMountedLogic(maxQuestionSuggestionsLogic)
    const { activeSuggestionGroup, suggestionGroups } = useValues(logic)
    const { setActiveGroup } = useActions(logic)

    useClickOutside([suggestionListRef], () => {
        if (activeSuggestionGroup) {
            setActiveGroup(null)
        }
    })

    return (
        <div className="flex flex-col items-center justify-center w-[min(48rem,100%)] gap-y-2">
            <h3 className="text-center text-xs font-medium mb-0 text-secondary">
                {activeSuggestionGroup ? activeSuggestionGroup.label : 'Ask Max about'}
            </h3>
            {!activeSuggestionGroup ? (
                <ul className="flex items-center justify-center flex-wrap gap-x-2 gap-y-1.5">
                    {suggestionGroups.map((group, index) => (
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
                                        setActiveGroup(index)
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
                                    setActiveGroup(null)
                                }}
                                size="small"
                                type="tertiary"
                                disabledReason={
                                    !dataProcessingAccepted ? 'Please accept OpenAI processing data' : undefined
                                }
                                title={suggestion.label}
                                className="[&_span]:line-clamp-1 [&_span]:break-all [&>span]:flex"
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
