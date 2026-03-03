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
import { FloatingSuggestionsDisplay } from './FloatingSuggestionsDisplay'
import { SidebarQuestionInput } from './SidebarQuestionInput'

export function SidebarQuestionInputWithSuggestions({
    hideSuggestions = false,
}: {
    hideSuggestions?: boolean
}): JSX.Element {
    const { dataProcessingAccepted, dataProcessingApprovalDisabledReason, activeSuggestionGroup } = useValues(maxLogic)
    const { setActiveGroup } = useActions(maxLogic)
    const { agentMode } = useValues(maxThreadLogic)
    const { coreMemory, coreMemoryLoading } = useValues(maxSettingsLogic)

    const [settingsModalOpen, setSettingsModalOpen] = useState(false)

    const handleSettingsClick = (): void => {
        setSettingsModalOpen(true)
    }

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
