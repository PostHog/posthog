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
            title="Estimate Experiment Traffic"
            description="Choose an event to estimate the number of users who will be exposed to your experiment. We'll use data from the last 14 days to calculate the minimum sample size and estimated duration for your experiment."
        >
            <ActionFilter
                bordered
                hideRename={true}
                typeKey="running-time-calculator"
                filters={filters}
                entitiesLimit={1}
                mathAvailability={MathAvailability.None}
                setFilters={({ events }: Partial<FilterType>) => {
                    if (!events || events.length === 0) {
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
