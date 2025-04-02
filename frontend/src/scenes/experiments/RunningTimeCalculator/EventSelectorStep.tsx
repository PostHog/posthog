import { useActions, useValues } from 'kea'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'

import { NodeKind } from '~/queries/schema/schema-general'
import { FilterType } from '~/types'

import { experimentLogic } from '../experimentLogic'
import { runningTimeCalculatorLogic } from './runningTimeCalculatorLogic'
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
        <div className="space-y-6">
            <div className="rounded bg-light p-4 space-y-3">
                <div className="flex items-center gap-2">
                    <span className="rounded-full bg-muted text-white w-6 h-6 flex items-center justify-center font-semibold">
                        1
                    </span>
                    <h4 className="font-semibold m-0">Select an Event</h4>
                </div>
                <p className="text-muted">
                    Choose an event to analyze. We'll use historical data from this event to estimate the experiment
                    duration.
                </p>
                <div className="space-y-2">
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
                </div>
            </div>
        </div>
    )
}
