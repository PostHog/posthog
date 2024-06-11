import { IconTrash } from '@posthog/icons'
import { LemonButton, Popover } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { TaxonomicFilterGroupType, TaxonomicFilterValue } from 'lib/components/TaxonomicFilter/types'
import { UniversalFilterValue } from 'lib/components/UniversalFilters/UniversalFilters'
import { universalFiltersLogic } from 'lib/components/UniversalFilters/universalFiltersLogic'
import { useState } from 'react'

import { PropertyFilterType } from '~/types'

import { playerSettingsLogic } from '../player/playerSettingsLogic'

export interface ReplayTaxonomicFiltersProps {
    onChange: (value: TaxonomicFilterValue, item?: any) => void
}

export function ReplayTaxonomicFilters({ onChange }: ReplayTaxonomicFiltersProps): JSX.Element {
    const { filterGroup } = useValues(universalFiltersLogic)

    const filters = filterGroup.values as UniversalFilterValue[]
    // const filters = rootFilters.values as UniversalFilterValue[]

    const hasConsoleLogLevelFilter = filters.find(
        (f) => f.type === PropertyFilterType.Recording && f.key === 'console_log_level'
    )
    const hasConsoleLogQueryFilter = filters.find(
        (f) => f.type === PropertyFilterType.Recording && f.key === 'console_log_query'
    )

    return (
        <div className="grid grid-cols-2 gap-4 px-1 pt-1.5 pb-2.5">
            <section>
                <h5 className="mx-2 my-1">Session properties</h5>
                <ul className="space-y-px">
                    <LemonButton
                        size="small"
                        fullWidth
                        onClick={() => onChange('console_log_level', {})}
                        disabledReason={
                            hasConsoleLogLevelFilter ? 'Only one console log level filter allowed' : undefined
                        }
                    >
                        Console log level
                    </LemonButton>
                    <LemonButton
                        size="small"
                        fullWidth
                        onClick={() => onChange('console_log_query', {})}
                        disabledReason={
                            hasConsoleLogQueryFilter ? 'Only one console log query filter allowed' : undefined
                        }
                    >
                        Console log text
                    </LemonButton>
                </ul>
            </section>

            <PersonProperties onChange={onChange} />
        </div>
    )
}

const PersonProperties = ({ onChange }: { onChange: ReplayTaxonomicFiltersProps['onChange'] }): JSX.Element => {
    const { quickFilterProperties: properties } = useValues(playerSettingsLogic)
    const { setQuickFilterProperties } = useActions(playerSettingsLogic)

    const [showPropertySelector, setShowPropertySelector] = useState<boolean>(false)

    return (
        <section>
            <h5 className="mx-2 my-1">Person properties</h5>
            <ul className="space-y-px">
                {properties.map((property) => (
                    <LemonButton
                        key={property}
                        size="small"
                        fullWidth
                        sideAction={{
                            onClick: () => {
                                const newProperties = properties.filter((p) => p != property)
                                setQuickFilterProperties(newProperties)
                            },
                            icon: <IconTrash />,
                        }}
                        onClick={() => onChange(property, { propertyFilterType: PropertyFilterType.Person })}
                    >
                        <PropertyKeyInfo value={property} />
                    </LemonButton>
                ))}
                <Popover
                    visible={showPropertySelector}
                    onClickOutside={() => setShowPropertySelector(false)}
                    placement="right-start"
                    overlay={
                        <TaxonomicFilter
                            onChange={(_, value) => {
                                properties.push(value as string)
                                setQuickFilterProperties([...properties])
                                setShowPropertySelector(false)
                            }}
                            taxonomicGroupTypes={[TaxonomicFilterGroupType.PersonProperties]}
                            excludedProperties={{ [TaxonomicFilterGroupType.PersonProperties]: properties }}
                        />
                    }
                >
                    <LemonButton size="small" onClick={() => setShowPropertySelector(!showPropertySelector)} fullWidth>
                        Add property
                    </LemonButton>
                </Popover>
            </ul>
        </section>
    )
}
