import { DismissableLayer } from '@radix-ui/react-dismissable-layer'
import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconGear } from '@posthog/icons'
import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { cn } from 'lib/utils/css-classes'
import { MaxMemorySettings } from 'scenes/settings/environment/MaxMemorySettings'
import { maxSettingsLogic } from 'scenes/settings/environment/maxSettingsLogic'

import { AgentMode } from '~/queries/schema/schema-assistant-messages'

import { capabilitiesForGrouping, capabilityGroupingFromVariant } from '../maxCapabilities'
import { QUESTION_SUGGESTIONS_DATA, RESEARCH_SUGGESTIONS_DATA, maxLogic } from '../maxLogic'
import { maxThreadLogic } from '../maxThreadLogic'
import { CAPABILITY_CARDS_HEIGHT_PX, CapabilityBadges, CapabilitySuggestions } from './CapabilityBadges'
import { FloatingSuggestionsDisplay } from './FloatingSuggestionsDisplay'
import { SidebarQuestionInput } from './SidebarQuestionInput'

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
    const { featureFlags } = useValues(featureFlagLogic)

    const [settingsModalOpen, setSettingsModalOpen] = useState(false)
    const [selectedCapability, setSelectedCapability] = useState<string | null>(null)

    const handleSettingsClick = (): void => {
        setSettingsModalOpen(true)
    }

    // Capability badges (same experiment as the homepage) replace the pills — except in Research
    // mode, which keeps its own tailored suggestions.
    const grouping = capabilityGroupingFromVariant(featureFlags[FEATURE_FLAGS.MAX_HOMEPAGE_CAPABILITIES])
    const showBadges = !!grouping && agentMode !== AgentMode.Research
    const capabilities = grouping ? capabilitiesForGrouping(grouping) : []
    const selectedCapabilityData = capabilities.find((capability) => capability.key === selectedCapability) ?? null

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
                setSelectedCapability(null)
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
                        <CapabilityBadges
                            capabilities={capabilities}
                            selectedKey={selectedCapability}
                            onSelect={(key) => {
                                setFillInHint(null)
                                setSelectedCapability(key)
                            }}
                        />
                        {selectedCapabilityData && (
                            <div className="w-full overflow-hidden" style={{ height: CAPABILITY_CARDS_HEIGHT_PX }}>
                                <CapabilitySuggestions
                                    capability={selectedCapabilityData}
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
