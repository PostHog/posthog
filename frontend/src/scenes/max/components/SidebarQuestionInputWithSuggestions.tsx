import { DismissableLayer } from '@radix-ui/react-dismissable-layer'
import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconGear } from '@posthog/icons'
import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'
import { MaxMemorySettings } from 'scenes/settings/environment/MaxMemorySettings'
import { maxSettingsLogic } from 'scenes/settings/environment/maxSettingsLogic'

import { AgentMode } from '~/queries/schema/schema-assistant-messages'

import { QUESTION_SUGGESTIONS_DATA, RESEARCH_SUGGESTIONS_DATA, maxLogic } from '../maxLogic'
import { maxThreadLogic } from '../maxThreadLogic'
import { HOMEPAGE_SUGGESTION_TOPICS } from '../suggestionTopics'
import { FloatingSuggestionsDisplay } from './FloatingSuggestionsDisplay'
import { SidebarQuestionInput } from './SidebarQuestionInput'
import { SUGGESTION_CARDS_HEIGHT_PX, TopicBadges, TopicSuggestions } from './TopicBadges'

export function SidebarQuestionInputWithSuggestions({
    hideSuggestions = false,
}: {
    hideSuggestions?: boolean
}): JSX.Element {
    const { dataProcessingAccepted, dataProcessingApprovalDisabledReason, activeSuggestionGroup } = useValues(maxLogic)
    const { setActiveGroup, setQuestion, focusInput, setFillInHint } = useActions(maxLogic)
    const { agentMode } = useValues(maxThreadLogic)
    const { askMax } = useActions(maxThreadLogic)
    const { coreMemory, coreMemoryLoading } = useValues(maxSettingsLogic)

    const [settingsModalOpen, setSettingsModalOpen] = useState(false)
    const [selectedTopic, setSelectedTopic] = useState<string | null>(null)

    const handleSettingsClick = (): void => {
        setSettingsModalOpen(true)
    }

    // SuggestionTopic badges replace the pills — except in Research mode, which keeps its own tailored suggestions.
    const showBadges = agentMode !== AgentMode.Research
    const selectedTopicData = HOMEPAGE_SUGGESTION_TOPICS.find((topic) => topic.key === selectedTopic) ?? null

    const tip =
        !coreMemoryLoading && !coreMemory?.text
            ? 'Tip: Run /init to initialize PostHog AI in this project'
            : agentMode === AgentMode.Research
              ? 'Try PostHog AI Research Mode for…'
              : 'Try PostHog AI for…'

    return (
        <DismissableLayer
            className="flex flex-col gap-3 w-full"
            onDismiss={() => {
                if (activeSuggestionGroup) {
                    setActiveGroup(null)
                }
                setSelectedTopic(null)
            }}
        >
            <SidebarQuestionInput />
            <div
                hidden={hideSuggestions}
                className={cn(
                    'flex flex-col items-center justify-center gap-y-2 transition-opacity duration-300 starting:opacity-100 [[hidden]]:opacity-0 [transition-behavior:allow-discrete]',
                    hideSuggestions && 'opacity-0'
                )}
            >
                <h3 className="text-center text-xs font-medium mb-0 text-secondary">{tip}</h3>
                {showBadges ? (
                    <div className="flex flex-col items-center gap-6 w-full">
                        <TopicBadges
                            topics={HOMEPAGE_SUGGESTION_TOPICS}
                            selectedKey={selectedTopic}
                            onSelect={(key) => {
                                setFillInHint(null)
                                setSelectedTopic(key)
                            }}
                        />
                        {selectedTopicData && (
                            <div className="w-full overflow-hidden" style={{ height: SUGGESTION_CARDS_HEIGHT_PX }}>
                                <TopicSuggestions
                                    topic={selectedTopicData}
                                    onType={setQuestion}
                                    onSubmit={(text) => askMax(text)}
                                    onFillIn={(hint) => {
                                        setFillInHint(hint)
                                        focusInput()
                                    }}
                                />
                            </div>
                        )}
                    </div>
                ) : (
                    <FloatingSuggestionsDisplay
                        type="secondary"
                        dataProcessingAccepted={dataProcessingAccepted}
                        dataProcessingApprovalDisabledReason={dataProcessingApprovalDisabledReason}
                        suggestionsData={
                            agentMode === AgentMode.Research ? RESEARCH_SUGGESTIONS_DATA : QUESTION_SUGGESTIONS_DATA
                        }
                        additionalSuggestions={[
                            <LemonButton
                                key="edit-max-memory"
                                onClick={handleSettingsClick}
                                size="xsmall"
                                type="secondary"
                                icon={<IconGear />}
                                tooltip="Edit PostHog AI memory"
                            />,
                        ]}
                    />
                )}
            </div>
            <LemonModal
                title="PostHog AI memory"
                isOpen={settingsModalOpen}
                onClose={() => setSettingsModalOpen(false)}
                width="40rem"
            >
                <MaxMemorySettings />
            </LemonModal>
        </DismissableLayer>
    )
}
