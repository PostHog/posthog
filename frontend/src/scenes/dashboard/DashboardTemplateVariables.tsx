import { useActions } from 'kea'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { dashboardTemplateVariablesLogic } from './DashboardTemplateVariablesLogic'

export function DashboardTemplateVariables(): JSX.Element {
    const { setProperties } = useActions(dashboardTemplateVariablesLogic)
    // const { filters } = useValues(dashboardVariablesLogic)

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

    const dashboard = {
        id: 1,
    }

    const signUpFlowEvents = [
        {
            name: 'Created Account',
            required: true,
            id: 1,
        },
        // {
        //     name: 'Homepage pageview',
        //     required: true,
        // },
        // {
        //     name: 'Sign Up page pageview',
        //     required: false,
        // },
        // {
        //     name: 'Activation event',
        //     required: false,
        // },
    ]
    return (
        <div>
            <h3>Variables</h3>
            <div>
                {signUpFlowEvents.map((variable) => (
                    <>
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
                            <PropertyFilters
                                onChange={setProperties}
                                pageKey={'dashboard_' + dashboard?.id + '_variable' + variable.id}
                                // propertyFilters={filters.properties}
                                taxonomicGroupTypes={[
                                    TaxonomicFilterGroupType.EventProperties,
                                    TaxonomicFilterGroupType.PersonProperties,
                                    TaxonomicFilterGroupType.EventFeatureFlags,
                                    // ...groupsTaxonomicTypes,
                                    TaxonomicFilterGroupType.Cohorts,
                                    TaxonomicFilterGroupType.Elements,
                                ]}
                            />
                        </div>
                    </>
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
