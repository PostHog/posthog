import { useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { infiniteListLogic } from 'lib/components/TaxonomicFilter/infiniteListLogic'
import { TaxonomicFilterGroupType, TaxonomicFilterRenderProps } from 'lib/components/TaxonomicFilter/types'
import { universalFiltersLogic } from 'lib/components/UniversalFilters/universalFiltersLogic'

import { getFilterLabel } from '~/taxonomy/helpers'
import { PropertyFilterType } from '~/types'

export const isReplayTaxonomicFilterProperty = (x: unknown): x is ReplayTaxonomicFilterProperty => {
    return typeof x === 'object' && x !== null && 'taxonomicFilterGroup' in x
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
    let filters: any[] = []
    try {
        const logic = universalFiltersLogic.findMounted()
        if (logic) {
            filters = logic.values.filterGroup.values
        }
    } catch {
        // Logic not mounted, ignore
    }

    const hasFilter = (key: string): boolean => {
        return !!filters.find((f) => f.type === PropertyFilterType.Recording && f.key === key)
    }

    const theInfiniteListLogic = infiniteListLogic(infiniteListLogicProps)
    const { items, searchQuery } = useValues(theInfiniteListLogic)
    const shouldFilter = !!searchQuery
    const propsToShow = shouldFilter
        ? items.results.filter((x): x is ReplayTaxonomicFilterProperty => isReplayTaxonomicFilterProperty(x))
        : replayTaxonomicFiltersProperties
    return (
        <div className="px-1 pt-1.5 pb-2.5">
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
        </div>
    )
}
