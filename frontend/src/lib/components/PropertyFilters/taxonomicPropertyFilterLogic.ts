import { kea } from 'kea'
import { AnyPropertyFilter } from '~/types'
import { DisplayMode } from './components/TaxonomicPropertyFilter'
import { personPropertiesModel } from '~/models/personPropertiesModel'
import { cohortsModel } from '~/models/cohortsModel'

import { taxonomicPropertyFilterLogicType } from './taxonomicPropertyFilterLogicType'
export const taxonomicPropertyFilterLogic = kea<taxonomicPropertyFilterLogicType>({
    props: {} as {
        pageKey: string
        index: number
        onChange?: null | ((filters: AnyPropertyFilter[]) => void)
    },
    key: (props) => `${props.pageKey}-${props.index}`,

    actions: () => ({
        update: true,
        setSearchQuery: (searchQuery: string) => ({ searchQuery }),
        setSelectedItemKey: (selectedItemKey: number | null) => ({ selectedItemKey }),
        setDisplayMode: (displayMode: DisplayMode) => ({
            displayMode,
        }),
    }),

    selectors: {
        personProperties: [
            () => [],
            () => {
                return personPropertiesModel.values.personProperties.map((property) => ({
                    ...property,
                    key: property.name,
                }))
            },
        ],
        cohorts: [
            () => [],
            () => {
                return cohortsModel.values.cohorts.map((cohort) => ({
                    ...cohort,
                    key: cohort.id,
                    name: cohort.name || '',
                }))
            },
        ],
    },
})
