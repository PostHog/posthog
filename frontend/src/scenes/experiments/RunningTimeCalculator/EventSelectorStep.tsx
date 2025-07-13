import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'

import { NodeKind } from '~/queries/schema/schema-general'
import { FilterType } from '~/types'

import { RunningTimeCalculatorModalStep } from './RunningTimeCalculatorModalStep'
import { ExposureEstimateConfig } from './runningTimeCalculatorLogic'

/**
 * Converts an ExposureEstimateConfig to a FilterType
 */
const exposureEstimateConfigToFilter = ({ eventFilter }: ExposureEstimateConfig): FilterType => {
    if (!eventFilter) {
        return {
            events: [],
            actions: [],
        }
    }

    return {
        actions:
            eventFilter.entityType === TaxonomicFilterGroupType.Actions
                ? [
                      {
                          id: eventFilter.event ? Number(eventFilter.event) : 0,
                          kind: NodeKind.ActionsNode,
                          type: 'actions',
                          name: eventFilter.name || '',
                          properties: eventFilter.properties || [],
                      },
                  ]
                : [],
        events:
            eventFilter.entityType === TaxonomicFilterGroupType.Events
                ? [
                      {
                          id: eventFilter.event || '$pageview',
                          kind: NodeKind.EventsNode,
                          type: 'events',
                          name: eventFilter.name || '$pageview',
                          properties: eventFilter.properties || [],
                      },
                  ]
                : [],
    }
}

export const EventSelectorStep = ({
    exposureEstimateConfig,
    onSetFilter,
}: {
    exposureEstimateConfig: ExposureEstimateConfig | null
    onSetFilter: (filter: Record<string, any>) => void
}): JSX.Element => {
    // If exposureEstimateConfig is null, we use the default filter
    const filter = exposureEstimateConfig
        ? exposureEstimateConfigToFilter(exposureEstimateConfig)
        : {
              events: [
                  {
                      id: '$pageview',
                      kind: NodeKind.EventsNode,
                      type: 'events',
                      name: '$pageview',
                      properties: [],
                  },
              ],
          }

    return (
        <RunningTimeCalculatorModalStep
            stepNumber={1}
            title="Estimate experiment traffic"
            description="Choose an event to estimate the number of users who will be exposed to your experiment. We'll use data from the last 14 days to calculate the minimum sample size and estimated duration for your experiment."
        >
            <ActionFilter
                bordered
                hideRename={true}
                typeKey="running-time-calculator"
                filters={filter}
                actionsTaxonomicGroupTypes={[TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.Actions]}
                entitiesLimit={1}
                mathAvailability={MathAvailability.None}
                setFilters={({ events, actions }: Partial<FilterType>) => {
                    const eventFilter = events?.[0] || actions?.[0]

                    if (!eventFilter) {
                        return
                    }

                    onSetFilter(eventFilter)
                }}
            />
        </RunningTimeCalculatorModalStep>
    )
}
