import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconInfo, IconPinFilled } from '@posthog/icons'
import { LemonButton, Popover, Tooltip } from '@posthog/lemon-ui'

import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { infiniteListLogic } from 'lib/components/TaxonomicFilter/infiniteListLogic'
import {
    TaxonomicDefinitionTypes,
    TaxonomicFilterGroupType,
    TaxonomicFilterRenderProps,
} from 'lib/components/TaxonomicFilter/types'
import { universalFiltersLogic } from 'lib/components/UniversalFilters/universalFiltersLogic'

import { getFilterLabel } from '~/taxonomy/helpers'
import { PropertyFilterType } from '~/types'

import { playerSettingsLogic } from '../player/playerSettingsLogic'

export const isReplayTaxonomicFilterProperty = (x: TaxonomicDefinitionTypes): x is ReplayTaxonomicFilterProperty => {
    return (x as ReplayTaxonomicFilterProperty).taxonomicFilterGroup !== undefined
}

export type ReplayTaxonomicFiltersProps = Pick<TaxonomicFilterRenderProps, 'onChange' | 'infiniteListLogicProps'>

export interface ReplayTaxonomicFilterProperty {
    key: string
    name: string
    propertyFilterType: PropertyFilterType
    taxonomicFilterGroup: TaxonomicFilterGroupType
}

export const replayTaxonomicFiltersProperties: ReplayTaxonomicFilterProperty[] = [
    {
        key: 'visited_page',
        name: getFilterLabel('visited_page', TaxonomicFilterGroupType.Replay),
        propertyFilterType: PropertyFilterType.Recording,
        taxonomicFilterGroup: TaxonomicFilterGroupType.Replay,
    },
    {
        key: 'snapshot_source',
        name: getFilterLabel('snapshot_source', TaxonomicFilterGroupType.Replay),
        propertyFilterType: PropertyFilterType.Recording,
        taxonomicFilterGroup: TaxonomicFilterGroupType.Replay,
    },
    {
        key: 'level',
        name: getFilterLabel('level', TaxonomicFilterGroupType.LogEntries),
        propertyFilterType: PropertyFilterType.LogEntry,
        taxonomicFilterGroup: TaxonomicFilterGroupType.LogEntries,
    },
    {
        key: 'message',
        name: getFilterLabel('message', TaxonomicFilterGroupType.LogEntries),
        propertyFilterType: PropertyFilterType.LogEntry,
        taxonomicFilterGroup: TaxonomicFilterGroupType.LogEntries,
    },
    {
        key: 'comment_text',
        name: getFilterLabel('comment_text', TaxonomicFilterGroupType.Replay),
        propertyFilterType: PropertyFilterType.Recording,
        taxonomicFilterGroup: TaxonomicFilterGroupType.Replay,
    },
]

export function ReplayTaxonomicFilters({ onChange, infiniteListLogicProps }: ReplayTaxonomicFiltersProps): JSX.Element {
    const {
        filterGroup: { values: filters },
    } = useValues(universalFiltersLogic)

    const hasFilter = (key: string): boolean => {
        return !!filters.find((f) => f.type === PropertyFilterType.Recording && f.key === key)
    }

    const theInfiniteListLogic = infiniteListLogic(infiniteListLogicProps)
    const { items, searchQuery } = useValues(theInfiniteListLogic)
    const shouldFilter = !!searchQuery
    // they all already are ReplayTaxonomicFilterProperty, but TS doesn't know that
    const propsToShow = shouldFilter
        ? items.results.filter((x): x is ReplayTaxonomicFilterProperty => isReplayTaxonomicFilterProperty(x))
        : replayTaxonomicFiltersProperties
    return (
        <div className="grid grid-cols-2 gap-4 px-1 pt-1.5 pb-2.5">
            <section>
                <h5 className="mt-1 mb-0">Replay properties</h5>
                <ul className="gap-y-px">
                    {propsToShow.map(({ key, name, propertyFilterType }) => {
                        return (
                            <LemonButton
                                key={key}
                                data-attr="custom-replay-property"
                                size="small"
                                fullWidth
                                onClick={() => onChange(key, { propertyFilterType: propertyFilterType })}
                                disabledReason={hasFilter(key) ? `${name} filter already added` : undefined}
                            >
                                {name}
                            </LemonButton>
                        )
                    })}
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
            <Tooltip title="Pin person properties to this list to let you quickly filter by the properties you care about. Changes here only affect the list you see.">
                <h5 className="mt-1 mb-0 flex items-center gap-x-1">
                    <IconInfo className="text-lg" />
                    <span>Pinned person properties</span>
                </h5>
            </Tooltip>
            <ul className="gap-y-px">
                {properties.map((property) => (
                    <LemonButton
                        key={property}
                        data-attr="pinned-person-property"
                        size="small"
                        fullWidth
                        sideAction={{
                            onClick: () => {
                                const newProperties = properties.filter((p) => p != property)
                                setQuickFilterProperties(newProperties)
                            },
                            icon: <IconPinFilled />,
                            tooltip: 'Unpin from this quick list.',
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
