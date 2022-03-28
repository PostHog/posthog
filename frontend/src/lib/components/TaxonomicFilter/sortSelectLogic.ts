import { kea } from 'kea'
import { TaxonomicSortOptionType } from 'lib/components/TaxonomicFilter/types'
import { sortSelectLogicType } from './sortSelectLogicType'
import { getBreakpoint } from 'lib/utils/responsiveUtils'

export interface SortSelectLogicProps {
    taxonomicFilterLogicKey?: string
}

export const sortSelectLogic = kea<sortSelectLogicType<SortSelectLogicProps>>({
    path: ['lib', 'components', 'TaxonomicFilter', 'sortSelectLogic'],
    props: {} as SortSelectLogicProps,
    actions: {
        selectOption: (option: TaxonomicSortOptionType) => ({ option }),
    },
    reducers: {
        option: [
            TaxonomicSortOptionType.Auto as TaxonomicSortOptionType,
            {
                selectOption: (_, { option }) => option,
            },
        ],
    },
    windowValues: {
        truncateControlLabel: (window) => window.innerWidth < getBreakpoint('sm'),
    },
})
