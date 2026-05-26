import { kea, key, path, props, selectors } from 'kea'

import {
    TaxonomicFilterGroup,
    TaxonomicFilterGroupType,
    TaxonomicFilterLogicProps,
} from 'lib/components/TaxonomicFilter/types'
import { MaxContextTaxonomicFilterOption } from 'scenes/max/maxTypes'

import type { maxAIContextTaxonomicGroupsLogicType } from './maxAIContextTaxonomicGroupsLogicType'

export const maxAIContextTaxonomicGroupsLogic = kea<maxAIContextTaxonomicGroupsLogicType>([
    props({} as TaxonomicFilterLogicProps),
    key((props) => `${props.taxonomicFilterLogicKey}`),
    path((key) => ['lib', 'components', 'TaxonomicFilter', 'maxAIContextTaxonomicGroupsLogic', key]),

    selectors({
        maxContextOptions: [
            () => [(_, props) => props.maxContextOptions],
            (maxContextOptions) => maxContextOptions ?? [],
        ],
        maxAIContextTaxonomicGroups: [
            (s) => [s.maxContextOptions],
            (maxContextOptions: MaxContextTaxonomicFilterOption[]): TaxonomicFilterGroup[] => [
                {
                    name: 'On this page',
                    searchPlaceholder: 'elements from this page',
                    type: TaxonomicFilterGroupType.MaxAIContext,
                    options: maxContextOptions,
                    getName: (option: MaxContextTaxonomicFilterOption) => option.name,
                    getValue: (option: MaxContextTaxonomicFilterOption) => option.value,
                    getIcon: (option: MaxContextTaxonomicFilterOption) => {
                        const IconComponent = option.icon
                        return <IconComponent />
                    },
                    getPopoverHeader: () => 'On this page',
                },
            ],
        ],
    }),
])
