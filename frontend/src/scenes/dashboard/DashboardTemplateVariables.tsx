import { LemonButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { useEffect } from 'react'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { InsightType } from '~/types'
import { dashboardTemplateVariablesLogic } from './DashboardTemplateVariablesLogic'

export function DashboardTemplateVariables(): JSX.Element {
    const { setFilterGroups } = useActions(dashboardTemplateVariablesLogic)
    const { filterGroups } = useValues(dashboardTemplateVariablesLogic)

    const dashboardId = 1

    const signUpFlowEvents = [
        {
            name: 'Created Account',
            required: true,
            id: 1,
            defaultEvent: {
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
        },
        {
            name: 'Homepage pageview',
            required: true,
            defaultEvent: {
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
        },
        {
            name: 'Sign Up page pageview',
            required: false,
            defaultEvent: undefined,
        },
        {
            name: 'Activation event',
            required: false,
            defaultEvent: undefined,
        },
    ]
    useEffect(() => {
        setFilterGroups(
            signUpFlowEvents.reduce((acc, variable) => {
                acc[variable.name] = {
                    insight: InsightType.TRENDS,
                    events: [variable.defaultEvent],
                }
                return acc
            }, {})
        )
    }, [])

    function createDashboard(): void {
        window.alert('create dashboard with the following filters: ' + JSON.stringify(filterGroups))
    }

    return (
        <div>
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
                            {filterGroups && filterGroups[variable.name] && (
                                <ActionFilter
                                    filters={filterGroups[variable.name]}
                                    setFilters={(filters) => setFilterGroups({ [variable.name]: filters })}
                                    typeKey={'dashboard_' + dashboardId + '_variable_' + variable.name}
                                    buttonCopy={''}
                                    hideDeleteBtn={true}
                                    hideRename={true}
                                    hideDuplicate={true}
                                    entitiesLimit={1}
                                />
                            )}
                        </div>
                    </div>
                ))}
                <LemonButton onClick={createDashboard}>Create dashboard</LemonButton>
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
