import { IconGear } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import { DismissableLayer } from '@radix-ui/react-dismissable-layer'
import { useActions, useMountedLogic, useValues } from 'kea'
import { router } from 'kea-router'

import { sidePanelSettingsLogic } from '~/layout/navigation-3000/sidepanel/panels/sidePanelSettingsLogic'

import { maxLogic } from './maxLogic'
import { maxQuestionSuggestionsLogic } from './maxQuestionSuggestionsLogic'
import { QuestionInput } from './QuestionInput'

export function QuestionInputWithSuggestions(): JSX.Element {
    const { dataProcessingAccepted } = useValues(maxLogic)
    const { askMax, setQuestion, focusInput } = useActions(maxLogic)
    const { openSettingsPanel } = useActions(sidePanelSettingsLogic)

    const logic = useMountedLogic(maxQuestionSuggestionsLogic)
    const { activeSuggestionGroup, suggestionGroups } = useValues(logic)
    const { setActiveGroup } = useActions(logic)

    return (
        <DismissableLayer
            className="flex flex-col gap-3"
            onDismiss={() => {
                if (activeSuggestionGroup) {
                    setActiveGroup(null)
                }
            }}
        >
            <QuestionInput />
            <div className="flex flex-col items-center justify-center gap-y-2">
                <h3 className="text-center text-xs font-medium mb-0 text-secondary">
                    {activeSuggestionGroup ? activeSuggestionGroup.label : 'Ask Max about'}
                </h3>
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
            </div>
        </DismissableLayer>
    )
}
