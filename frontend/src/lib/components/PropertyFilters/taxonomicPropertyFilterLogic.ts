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
        initialDisplayMode: DisplayMode
    },
    key: (props) => `${props.pageKey}-${props.index}`,

    actions: () => ({
        update: true,
        setSearchQuery: (searchQuery: string) => ({ searchQuery }),
        setSelectedItemKey: (selectedItemKey: string | number | null) => ({ selectedItemKey }),
        setDisplayMode: (displayMode: DisplayMode) => ({
            displayMode,
        }),
    }),

    reducers: ({ props }) => ({
        searchQuery: [
            '',
            {
                setSearchQuery: (_, { searchQuery }) => searchQuery,
            },
        ],
        selectedItemKey: [
            null as string | number | null,
            {
                setSelectedItemKey: (_, { selectedItemKey }) => selectedItemKey,
            },
        ],
        displayMode: [
            props.initialDisplayMode,
            {
                setDisplayMode: (_, { displayMode }) => displayMode,
            },
        ],
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
