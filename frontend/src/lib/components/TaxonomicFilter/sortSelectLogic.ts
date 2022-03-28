import { kea } from 'kea'
import { TaxonomicSortOptionType } from 'lib/components/TaxonomicFilter/types'
import { sortSelectLogicType } from './sortSelectLogicType'

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
})
