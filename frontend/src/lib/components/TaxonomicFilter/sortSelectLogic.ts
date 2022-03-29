import { kea } from 'kea'
import {
    TaxonomicFilterGroupType,
    TaxonomicFilterLogicProps,
    TaxonomicSortOptionType,
} from 'lib/components/TaxonomicFilter/types'
import { sortSelectLogicType } from './sortSelectLogicType'
import { getBreakpoint } from 'lib/utils/responsiveUtils'
import {
    renderOptionIcon,
    renderOptionLabel,
    TAXONOMIC_COHORTS_SORT_ALLOWLIST,
    TAXONOMIC_SORT_ALLOWLIST,
    TaxonomicOption,
    TaxonomicSortDirection,
} from 'lib/components/LemonSelect/utils'
import { LemonSelectGroupOrFlatOptions } from 'lib/components/LemonSelect'
import { taxonomicFilterLogic } from 'lib/components/TaxonomicFilter/taxonomicFilterLogic'

export const sortSelectLogic = kea<sortSelectLogicType>({
    path: ['lib', 'components', 'TaxonomicFilter', 'sortSelectLogic'],
    props: {} as TaxonomicFilterLogicProps,
    key: (props) => `${props.taxonomicFilterLogicKey}`,
    connect: (props: TaxonomicFilterLogicProps) => ({
        values: [taxonomicFilterLogic(props), ['activeTab']],
    }),
    actions: {
        selectOption: (group: TaxonomicFilterGroupType, option: TaxonomicSortOptionType) => ({ group, option }),
    },
    reducers: {
        selectedOptionMap: [
            {} as Record<TaxonomicFilterGroupType, TaxonomicSortOptionType>,
            {
                selectOption: (state, { group, option }) => ({ ...state, [group]: option }),
            },
        ],
    },
    selectors: {
        defaultOptions: [
            (s) => [s.activeTab],
            (groupType): LemonSelectGroupOrFlatOptions<TaxonomicOption> => ({
                ['Sort by']: Object.fromEntries(
                    Object.entries({
                        [TaxonomicSortOptionType.Auto]: {
                            label: renderOptionLabel('Automatic'),
                            icon: renderOptionIcon(TaxonomicSortDirection.None),
                            available: [...TAXONOMIC_SORT_ALLOWLIST, ...TAXONOMIC_COHORTS_SORT_ALLOWLIST],
                        },
                        [TaxonomicSortOptionType.VerifiedAsc]: {
                            label: renderOptionLabel('Verified', 'first'),
                            icon: renderOptionIcon(TaxonomicSortDirection.Ascending),
                            available: TAXONOMIC_SORT_ALLOWLIST,
                        },
                        [TaxonomicSortOptionType.VerifiedDesc]: {
                            label: renderOptionLabel('Verified', 'last'),
                            icon: renderOptionIcon(TaxonomicSortDirection.Descending),
                            available: TAXONOMIC_SORT_ALLOWLIST,
                        },
                        [TaxonomicSortOptionType.AlphabeticAsc]: {
                            label: renderOptionLabel('Alphabetical', 'A to Z'),
                            icon: renderOptionIcon(TaxonomicSortDirection.Ascending),
                            available: TAXONOMIC_SORT_ALLOWLIST,
                        },
                        [TaxonomicSortOptionType.AlphabeticDesc]: {
                            label: renderOptionLabel('Alphabetical', 'Z to A'),
                            icon: renderOptionIcon(TaxonomicSortDirection.Descending),
                            available: TAXONOMIC_SORT_ALLOWLIST,
                        },
                        [TaxonomicSortOptionType.CreatedAtAsc]: {
                            label: renderOptionLabel('Created', 'new to old'),
                            icon: renderOptionIcon(TaxonomicSortDirection.Ascending),
                            available: TAXONOMIC_SORT_ALLOWLIST,
                        },
                        [TaxonomicSortOptionType.CreatedAtDesc]: {
                            label: renderOptionLabel('Created', 'old to new'),
                            icon: renderOptionIcon(TaxonomicSortDirection.Descending),
                            available: TAXONOMIC_SORT_ALLOWLIST,
                        },
                        [TaxonomicSortOptionType.LastSeenAsc]: {
                            label: renderOptionLabel('Last seen', 'new to old'),
                            icon: renderOptionIcon(TaxonomicSortDirection.Ascending),
                            available: TAXONOMIC_SORT_ALLOWLIST,
                        },
                        [TaxonomicSortOptionType.LastSeenDesc]: {
                            label: renderOptionLabel('Last seen', 'old to new'),
                            icon: renderOptionIcon(TaxonomicSortDirection.Descending),
                            available: TAXONOMIC_SORT_ALLOWLIST,
                        },
                        [TaxonomicSortOptionType.UpdatedAsc]: {
                            label: renderOptionLabel('Updated', 'new to old'),
                            icon: renderOptionIcon(TaxonomicSortDirection.Ascending),
                            available: TAXONOMIC_SORT_ALLOWLIST,
                        },
                        [TaxonomicSortOptionType.UpdatedDesc]: {
                            label: renderOptionLabel('Updated', 'old to new'),
                            icon: renderOptionIcon(TaxonomicSortDirection.Descending),
                            available: TAXONOMIC_SORT_ALLOWLIST,
                        },
                        /** Cohorts */
                        [TaxonomicSortOptionType.TotalCountAsc]: {
                            label: renderOptionLabel('Total count', 'least to most'),
                            icon: renderOptionIcon(TaxonomicSortDirection.Ascending),
                            available: TAXONOMIC_COHORTS_SORT_ALLOWLIST,
                        },
                        [TaxonomicSortOptionType.TotalCountDesc]: {
                            label: renderOptionLabel('Updated', 'most to least'),
                            icon: renderOptionIcon(TaxonomicSortDirection.Descending),
                            available: TAXONOMIC_COHORTS_SORT_ALLOWLIST,
                        },
                        [TaxonomicSortOptionType.LastCalculatedAsc]: {
                            label: renderOptionLabel('Last calculated', 'new to old'),
                            icon: renderOptionIcon(TaxonomicSortDirection.Ascending),
                            available: TAXONOMIC_COHORTS_SORT_ALLOWLIST,
                        },
                        [TaxonomicSortOptionType.LastCalculatedDesc]: {
                            label: renderOptionLabel('Last calculated', 'old to new'),
                            icon: renderOptionIcon(TaxonomicSortDirection.Descending),
                            available: TAXONOMIC_COHORTS_SORT_ALLOWLIST,
                        },
                    })
                        .filter(([, { available }]) => available.includes(groupType))
                        .map((v) => v)
                ),
            }),
        ],
    },
    windowValues: {
        truncateControlLabel: (window) => window.innerWidth < getBreakpoint('sm'),
    },
})
