import { LemonButton } from '@posthog/lemon-ui'
import { useState } from 'react'
import { HogFunctionSelectionList } from 'scenes/pipeline/hogfunctions/list/HogFunctionSelectionList'
import { HogFunctionTemplateList } from 'scenes/pipeline/hogfunctions/list/HogFunctionTemplateList'
export interface AlertDestinationSelectorProps {
    selectedDestinationIds: string[]
    setSelectedDestinationIds: (ids: string[]) => void
}

export const INSIGHT_ALERT_DESTINATION_LOGIC_KEY = 'insightAlertDestination'
const type = 'internal_destination'
const subTemplateId = 'insight-alert-firing'
const filters = {}

export function AlertDestinationSelector({
    selectedDestinationIds,
    setSelectedDestinationIds,
}: AlertDestinationSelectorProps): JSX.Element {
    const [showNewDestination, setShowNewDestination] = useState(false)

    return showNewDestination ? (
        <HogFunctionTemplateList
            defaultFilters={{}}
            type={type}
            subTemplateId={subTemplateId}
            forceFilters={{ filters }}
            extraControls={
                <>
                    <LemonButton type="secondary" size="small" onClick={() => setShowNewDestination(false)}>
                        Cancel
                    </LemonButton>
                </>
            }
        />
    ) : (
        <div className="space-y-2">
            <p className="text-muted">
                Select one or more destinations to trigger when this alert fires. You can create new destinations using
                the button above or manage them in the Data Pipeline section.
            </p>
            <HogFunctionSelectionList
                logicKey={INSIGHT_ALERT_DESTINATION_LOGIC_KEY}
                forceFilters={{ filters }}
                type={type}
                selectedHogFunctionIds={selectedDestinationIds}
                onSelectionChange={setSelectedDestinationIds}
            />
            <div className="mt-2">
                <LemonButton type="tertiary" size="small" onClick={() => setShowNewDestination(true)}>
                    New destination
                </LemonButton>
            </div>
        </div>
    )
}
