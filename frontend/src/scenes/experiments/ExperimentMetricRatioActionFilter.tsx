import { LemonLabel } from 'lib/lemon-ui/LemonLabel'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'
import { ExperimentRatioMetric, NodeKind } from '~/queries/schema/schema-general'
import { FilterType } from '~/types'
import { commonActionFilterProps } from './Metrics/Selectors'

interface ExperimentMetricRatioActionFilterProps {
    metric: ExperimentRatioMetric
    type: 'numerator' | 'denominator'
    label: string
    buttonCopy: string
    typeKey: string
    mathAvailability: MathAvailability
    allowedMathTypes: string[]
    onUpdate: (updatedMetric: ExperimentRatioMetric) => void
}

export function ExperimentMetricRatioActionFilter({
    metric,
    type,
    label,
    buttonCopy,
    typeKey,
    mathAvailability,
    allowedMathTypes,
    onUpdate,
}: ExperimentMetricRatioActionFilterProps): JSX.Element {
    const currentValue = metric[type]

    const handleSetFilters = (filters: Partial<FilterType>): void => {
        if (filters.events?.[0]) {
            onUpdate({
                ...metric,
                [type]: {
                    kind: NodeKind.EventsNode,
                    event: filters.events[0].id,
                    name: filters.events[0].name,
                    math: filters.events[0].math,
                    math_property: filters.events[0].math_property,
                    properties: filters.events[0].properties,
                },
            })
        }
    }

    return (
        <div>
            <LemonLabel className="mb-1">{label}</LemonLabel>
            <ActionFilter
                bordered
                filters={{
                    events: [
                        {
                            id: currentValue.event || '',
                            name: currentValue.name || currentValue.event || '',
                            type: 'events',
                            kind: currentValue.kind,
                            event: currentValue.event,
                            math: currentValue.math,
                            math_property: currentValue.math_property,
                            properties: currentValue.properties,
                        },
                    ],
                    actions: [],
                    data_warehouse: [],
                }}
                setFilters={handleSetFilters}
                typeKey={typeKey}
                buttonCopy={buttonCopy}
                showSeriesIndicator={false}
                hideRename={true}
                entitiesLimit={1}
                showNumericalPropsOnly={type === 'numerator'}
                mathAvailability={mathAvailability}
                allowedMathTypes={allowedMathTypes}
                actionsTaxonomicGroupTypes={commonActionFilterProps.actionsTaxonomicGroupTypes?.filter(
                    (type) => type !== 'data_warehouse'
                )}
                propertiesTaxonomicGroupTypes={commonActionFilterProps.propertiesTaxonomicGroupTypes}
            />
        </div>
    )
}
