import { useValues } from 'kea'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TestAccountFilterSwitch } from 'lib/components/TestAccountFiltersSwitch'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'

import { groupsModel } from '~/models/groupsModel'
import { EntityTypes } from '~/types'

export type PipelineNodeFiltersProps = {
    description?: JSX.Element
}

export function PipelineNodeFilters({ description }: PipelineNodeFiltersProps): JSX.Element {
    const { groupsTaxonomicTypes } = useValues(groupsModel)

    return (
        <div className="border bg-bg-light rounded p-3 space-y-2">
            <LemonField name="filters" label="Filters by events and actions">
                {({ value, onChange }) => (
                    <>
                        <TestAccountFilterSwitch
                            checked={value?.filter_test_accounts ?? false}
                            onChange={(val) => onChange({ ...value, filter_test_accounts: val })}
                            fullWidth
                        />
                        <ActionFilter
                            bordered
                            filters={value ?? {}}
                            setFilters={(payload) => {
                                onChange({
                                    ...payload,
                                    filter_test_accounts: value?.filter_test_accounts,
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
                            buttonCopy="Add event filter"
                        />
                    </>
                )}
            </LemonField>

            <p className="italic text-muted-alt">{description}</p>
        </div>
    )
}
