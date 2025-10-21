import { DismissableLayer } from '@radix-ui/react-dismissable-layer'
import { useActions, useValues } from 'kea'

import { IconGear } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { maxSettingsLogic } from 'scenes/settings/environment/maxSettingsLogic'

import { sidePanelSettingsLogic } from '~/layout/navigation-3000/sidepanel/panels/sidePanelSettingsLogic'

import { maxLogic } from '../maxLogic'
import { FloatingSuggestionsDisplay } from './FloatingSuggestionsDisplay'
import { SidebarQuestionInput } from './SidebarQuestionInput'

export function SidebarQuestionInputWithSuggestions(): JSX.Element {
    const { dataProcessingAccepted, activeSuggestionGroup } = useValues(maxLogic)
    const { setActiveGroup } = useActions(maxLogic)
    const { coreMemory, coreMemoryLoading } = useValues(maxSettingsLogic)
    const { openSettingsPanel } = useActions(sidePanelSettingsLogic)

    const tip =
        !coreMemoryLoading && !coreMemory?.text
            ? 'Tip: Run /init to initialize PostHog AI in this project'
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
            <div className="flex flex-col items-center justify-center gap-y-2">
                <h3 className="text-center text-xs font-medium mb-0 text-secondary">{tip}</h3>
                <FloatingSuggestionsDisplay
                    type="secondary"
                    dataProcessingAccepted={dataProcessingAccepted}
                    additionalSuggestions={[
                        <LemonButton
                            key="edit-max-memory"
                            onClick={() =>
                                openSettingsPanel({ sectionId: 'environment-max', settingId: 'core-memory' })
                            }
                            size="xsmall"
                            type="secondary"
                            icon={<IconGear />}
                            tooltip="Edit PostHog AI memory"
                        />,
                    ]}
                />
            </div>
        </DismissableLayer>
    )
}
