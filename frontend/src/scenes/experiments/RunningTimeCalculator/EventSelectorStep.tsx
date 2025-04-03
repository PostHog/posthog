import { useActions, useValues } from 'kea'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'

import { NodeKind } from '~/queries/schema/schema-general'
import { FilterType } from '~/types'

import { experimentLogic } from '../experimentLogic'
import { runningTimeCalculatorLogic } from './runningTimeCalculatorLogic'
import { RunningTimeCalculatorModalStep } from './RunningTimeCalculatorModalStep'

export const EventSelectorStep = (): JSX.Element => {
    const { experimentId } = useValues(experimentLogic)

    const { eventConfig } = useValues(runningTimeCalculatorLogic({ experimentId }))
    const { setEventConfig } = useActions(runningTimeCalculatorLogic({ experimentId }))

    const filters = {
        events: [
            {
                id: '$pageview',
                kind: NodeKind.EventsNode,
                type: 'events',
                name: '$pageview',
                properties: [],
                ...eventConfig,
            },
        ],
    }

    return (
        <RunningTimeCalculatorModalStep
            stepNumber={1}
            title="Select an Event"
            description="Choose an event to analyze. We'll use historical data from this event to estimate the experiment duration."
        >
            <ActionFilter
                bordered
                hideRename={true}
                typeKey="running-time-calculator"
                filters={filters}
                entitiesLimit={1}
                mathAvailability={MathAvailability.None}
                setFilters={({ events }: Partial<FilterType>) => {
                    if (!events) {
                        return
                    }
                    setEventConfig({
                        event: events[0].id,
                        properties: events[0].properties,
                    })
                }}
            />
        </RunningTimeCalculatorModalStep>
    )
}
