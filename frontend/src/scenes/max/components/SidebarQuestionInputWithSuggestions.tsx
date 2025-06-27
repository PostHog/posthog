import { IconGear } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import { DismissableLayer } from '@radix-ui/react-dismissable-layer'
import { useActions, useValues } from 'kea'

import { sidePanelSettingsLogic } from '~/layout/navigation-3000/sidepanel/panels/sidePanelSettingsLogic'

import { maxLogic } from '../maxLogic'
import { SidebarQuestionInput } from './SidebarQuestionInput'
import { FloatingSuggestionsDisplay } from './FloatingSuggestionsDisplay'

export function SidebarQuestionInputWithSuggestions(): JSX.Element {
    const { dataProcessingAccepted, activeSuggestionGroup } = useValues(maxLogic)
    const { setActiveGroup } = useActions(maxLogic)
    const { openSettingsPanel } = useActions(sidePanelSettingsLogic)

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
                <h3 className="text-center text-xs font-medium mb-0 text-secondary">Ask Max about…</h3>
                <FloatingSuggestionsDisplay
                    type="secondary"
                    showSuggestions
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
                            tooltip="Edit Max's memory"
                        />,
                    ]}
                />
            </div>
        </DismissableLayer>
    )
}
