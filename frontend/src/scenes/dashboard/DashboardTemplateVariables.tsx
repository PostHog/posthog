import { useActions, useValues } from 'kea'
import { useEffect } from 'react'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { InsightType } from '~/types'
import { dashboardTemplateVariablesLogic } from './DashboardTemplateVariablesLogic'

export function DashboardTemplateVariables(): JSX.Element {
    const { setFilters } = useActions(dashboardTemplateVariablesLogic)
    const { filters } = useValues(dashboardTemplateVariablesLogic)

    const dashboardId = 1

    useEffect(() => {
        setFilters({
            insight: InsightType.TRENDS,
            events: [
                {
                    id: '$pageview',
                    name: '$pageview',
                    order: 0,
                    type: 'events',
                    properties: [
                        {
                            key: '$browser',
                            value: ['Chrome'],
                            operator: 'exact',
                            type: 'person',
                        },
                    ],
                },
            ],
        })
    }, [])

    // const [filters, setFilters] = useState<FilterType>({
    //     insight: InsightType.TRENDS,
    //     events: [
    //         {
    //             id: '$pageview',
    //             name: '$pageview',
    //             order: 0,
    //             type: 'events',
    //             properties: [
    //                 {
    //                     key: '$browser',
    //                     value: ['Chrome'],
    //                     operator: 'exact',
    //                     type: 'person',
    //                 },
    //             ],
    //         },
    //     ],
    // })

    const signUpFlowEvents = [
        {
            name: 'Created Account',
            required: true,
            id: 1,
        },
        {
            name: 'Homepage pageview',
            required: true,
        },
        {
            name: 'Sign Up page pageview',
            required: false,
        },
        {
            name: 'Activation event',
            required: false,
        },
    ]
    return (
        <div>
            <h3>Variables</h3>
            <div>
                {signUpFlowEvents.map((variable, index) => (
                    <div key={index}>
                        <div key={variable.name}>
                            <span>{variable.name}</span>{' '}
                            <span
                                style={{
                                    color: variable.required ? 'red' : 'green',
                                }}
                            >
                                {variable.required ? 'required' : 'optional'}
                            </span>
                        </div>
                        <div>
                            {filters && (
                                <ActionFilter
                                    filters={filters}
                                    setFilters={setFilters}
                                    typeKey={'dashboard_' + dashboardId + '_variable_' + variable.name}
                                    buttonCopy={''}
                                />
                            )}
                        </div>
                    </div>
                ))}
            </div>
        </div>
    )
}

// filters={filters}
//             setFilters={(payload: Partial<FilterType>): void => setFilters(payload)}
//             typeKey={`trends_${id.current}`}
//             buttonCopy="Add graph series"
//             showSeriesIndicator
//             entitiesLimit={
//                 isLifecycleFilter(filters) ||
//                 (isFilterWithDisplay(filters) &&
//                     filters.display &&
//                     SINGLE_SERIES_DISPLAY_TYPES.includes(filters.display))
//                     ? 1
//                     : alphabet.length
//             }
//             mathAvailability={
//                 filters.insight === InsightType.LIFECYCLE
//                     ? MathAvailability.None
//                     : filters.insight === InsightType.STICKINESS
//                     ? MathAvailability.ActorsOnly
//                     : MathAvailability.All
//             }
//             propertiesTaxonomicGroupTypes={[
//                 TaxonomicFilterGroupType.EventProperties,
//                 TaxonomicFilterGroupType.PersonProperties,
//                 TaxonomicFilterGroupType.EventFeatureFlags,
//                 ...groupsTaxonomicTypes,
//                 TaxonomicFilterGroupType.Cohorts,
//                 TaxonomicFilterGroupType.Elements,
//                 TaxonomicFilterGroupType.HogQLExpression,
//             ]}
//             {...props}
