import { LemonLabel, LemonSelect } from '@posthog/lemon-ui'
import { id } from 'chartjs-plugin-trendline'
import { useValues } from 'kea'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TestAccountFilterSwitch } from 'lib/components/TestAccountFiltersSwitch'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'

import { groupsModel } from '~/models/groupsModel'
import { AnyPropertyFilter, EntityTypes, FilterType, HogFunctionFiltersType } from '~/types'

import { hogFunctionConfigurationLogic } from '../hogFunctionConfigurationLogic'

function sanitizeActionFilters(filters?: FilterType): Partial<HogFunctionFiltersType> {
    if (!filters) {
        return {}
    }
    const sanitized: HogFunctionFiltersType = {}

    if (filters.events) {
        sanitized.events = filters.events.map((f) => ({
            id: f.id,
            type: 'events',
            name: f.name,
            order: f.order,
            properties: f.properties,
        }))
    }

    if (filters.actions) {
        sanitized.actions = filters.actions.map((f) => ({
            id: f.id,
            type: 'actions',
            name: f.name,
            order: f.order,
            properties: f.properties,
        }))
    }

    return sanitized
}

export function HogFunctionFilters(): JSX.Element {
    const { groupsTaxonomicTypes } = useValues(groupsModel)
    const { configuration } = useValues(hogFunctionConfigurationLogic)

    return (
        <div className="border bg-bg-light rounded p-3 space-y-2">
            <LemonField name="trigger" label="Trigger source">
                <LemonSelect
                    options={[
                        {
                            value: 'events',
                            label: 'Events',
                            labelInMenu: (
                                <div>
                                    Events
                                    <br />
                                    <span className="text-xs text-muted-alt">Incoming real-time PostHog events</span>
                                </div>
                            ),
                        },
                        {
                            value: 'activity_log',
                            label: 'Team activity',
                            labelInMenu: (
                                <div>
                                    Team activity
                                    <br />
                                    <span className="text-xs text-muted-alt">
                                        Changes in PostHog such as an Insight being created
                                    </span>
                                </div>
                            ),
                        },
                        {
                            value: 'alerts',
                            label: 'Alerts',
                            labelInMenu: (
                                <div>
                                    Alerts
                                    <br />
                                    <span className="text-xs text-muted-alt">
                                        React to alerts created in PostHog such as for an Insight threshold being
                                        reached
                                    </span>
                                </div>
                            ),
                        },
                    ]}
                />
            </LemonField>

            <LemonField name="filters" label="Filters">
                {({ value, onChange }) => (
                    <>
                        <TestAccountFilterSwitch
                            checked={value?.filter_test_accounts ?? false}
                            onChange={(filter_test_accounts) => onChange({ ...value, filter_test_accounts })}
                            fullWidth
                        />
                        <PropertyFilters
                            propertyFilters={value?.properties ?? []}
                            taxonomicGroupTypes={[
                                TaxonomicFilterGroupType.EventProperties,
                                TaxonomicFilterGroupType.PersonProperties,
                                TaxonomicFilterGroupType.EventFeatureFlags,
                                TaxonomicFilterGroupType.Elements,
                                TaxonomicFilterGroupType.HogQLExpression,
                            ]}
                            onChange={(properties: AnyPropertyFilter[]) => {
                                onChange({
                                    ...value,
                                    properties,
                                })
                            }}
                            pageKey={`HogFunctionPropertyFilters.${id}`}
                        />

                        <LemonLabel>Match event and actions</LemonLabel>
                        <p className="mb-0 text-muted-alt text-xs">
                            If set, the destination will only run if the <b>event matches any</b> of the below.
                        </p>
                        <ActionFilter
                            bordered
                            filters={value ?? {}}
                            setFilters={(payload) => {
                                onChange({
                                    ...value,
                                    ...sanitizeActionFilters(payload),
                                })
                            }}
                            typeKey="plugin-filters"
                            mathAvailability={MathAvailability.None}
                            hideRename
                            hideDuplicate
                            showNestedArrow={false}
                            actionsTaxonomicGroupTypes={[
                                TaxonomicFilterGroupType.Events,
                                TaxonomicFilterGroupType.Actions,
                            ]}
                            propertiesTaxonomicGroupTypes={[
                                TaxonomicFilterGroupType.EventProperties,
                                TaxonomicFilterGroupType.EventFeatureFlags,
                                TaxonomicFilterGroupType.Elements,
                                TaxonomicFilterGroupType.PersonProperties,
                                TaxonomicFilterGroupType.HogQLExpression,
                                ...groupsTaxonomicTypes,
                            ]}
                            propertyFiltersPopover
                            addFilterDefaultOptions={{
                                id: '$pageview',
                                name: '$pageview',
                                type: EntityTypes.EVENTS,
                            }}
                            buttonCopy="Add event matcher"
                        />
                    </>
                )}
            </LemonField>

            <LemonField name="masking" label="Trigger options">
                {({ value, onChange }) => (
                    <div className="flex items-center gap-1 flex-wrap">
                        <LemonSelect
                            options={[
                                {
                                    value: null,
                                    label: 'Run every time',
                                },
                                {
                                    value: 'all',
                                    label: 'Run once per interval',
                                },
                                {
                                    value: '{person.uuid}',
                                    label: 'Run once per person per interval',
                                },
                            ]}
                            value={value?.hash ?? null}
                            onChange={(val) =>
                                onChange({
                                    hash: val,
                                    ttl: value?.ttl ?? 60 * 30,
                                })
                            }
                        />
                        {configuration.masking?.hash ? (
                            <>
                                <div className="flex items-center gap-1 flex-wrap">
                                    <span>of</span>
                                    <LemonSelect
                                        value={value?.ttl}
                                        onChange={(val) => onChange({ ...value, ttl: val })}
                                        options={[
                                            {
                                                value: 5 * 60,
                                                label: '5 minutes',
                                            },
                                            {
                                                value: 15 * 60,
                                                label: '15 minutes',
                                            },
                                            {
                                                value: 30 * 60,
                                                label: '30 minutes',
                                            },
                                            {
                                                value: 60 * 60,
                                                label: '1 hour',
                                            },
                                            {
                                                value: 2 * 60 * 60,
                                                label: '2 hours',
                                            },
                                            {
                                                value: 4 * 60 * 60,
                                                label: '4 hours',
                                            },
                                            {
                                                value: 8 * 60 * 60,
                                                label: '8 hours',
                                            },
                                            {
                                                value: 12 * 60 * 60,
                                                label: '12 hours',
                                            },
                                            {
                                                value: 24 * 60 * 60,
                                                label: '24 hours',
                                            },
                                        ]}
                                    />
                                </div>
                                <div className="flex items-center gap-1 flex-wrap">
                                    <span>or until</span>
                                    <LemonSelect
                                        value={value?.threshold}
                                        onChange={(val) => onChange({ ...value, threshold: val })}
                                        options={[
                                            {
                                                value: null,
                                                label: 'Not set',
                                            },
                                            {
                                                value: 1000,
                                                label: '1000 events',
                                            },
                                            {
                                                value: 10000,
                                                label: '10,000 events',
                                            },
                                            {
                                                value: 100000,
                                                label: '100,000 events',
                                            },
                                            {
                                                value: 1000000,
                                                label: '1,000,000 events',
                                            },
                                        ]}
                                    />
                                </div>
                            </>
                        ) : null}
                    </div>
                )}
            </LemonField>
        </div>
    )
}
