import { useActions, useValues } from 'kea'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'

import { NodeKind } from '~/queries/schema/schema-general'
import { FilterType } from '~/types'

import { experimentLogic } from '../experimentLogic'
import { EventConfig, runningTimeCalculatorLogic } from './runningTimeCalculatorLogic'
import { RunningTimeCalculatorModalStep } from './RunningTimeCalculatorModalStep'

const exposureEstimateConfigToFilter = (exposureEstimateConfig: EventConfig | null): FilterType => ({
    events: [
        {
            id: exposureEstimateConfig?.event || '$pageview',
            kind: NodeKind.EventsNode,
            type: 'events',
            name: exposureEstimateConfig?.event || '$pageview',
            properties: exposureEstimateConfig?.properties || [],
        },
    ],
})

export const EventSelectorStep = (): JSX.Element => {
    const { experimentId } = useValues(experimentLogic)

    const { exposureEstimateConfig } = useValues(runningTimeCalculatorLogic({ experimentId }))
    const { setExposureEstimateConfig } = useActions(runningTimeCalculatorLogic({ experimentId }))

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
                filters={exposureEstimateConfigToFilter(exposureEstimateConfig)}
                entitiesLimit={1}
                mathAvailability={MathAvailability.None}
                setFilters={({ events }: Partial<FilterType>) => {
                    if (!events || events.length === 0) {
                        return
                    }
                    setExposureEstimateConfig({
                        event: events[0].id,
                        properties: events[0].properties,
                    })
                }}
            />
        </RunningTimeCalculatorModalStep>
    )
}
