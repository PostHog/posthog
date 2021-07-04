import { kea } from 'kea'
import { AnyPropertyFilter } from '~/types'
import { DisplayMode } from './components/TaxonomicPropertyFilter/TaxonomicPropertyFilter'
import { personPropertiesModel } from '~/models/personPropertiesModel'
import { cohortsModel } from '~/models/cohortsModel'
import { taxonomicPropertyFilterLogicType } from './taxonomicPropertyFilterLogicType'

export const taxonomicPropertyFilterLogic = kea<taxonomicPropertyFilterLogicType>({
    props: {} as {
        key: string
        onChange?: null | ((filters: AnyPropertyFilter[]) => void)
        initialDisplayMode?: DisplayMode
    },
    key: (props) => props.key,

    actions: () => ({
        update: true,
        setSearchQuery: (searchQuery: string) => ({ searchQuery }),
        setSelectedItemKey: (selectedItemKey: string | number | null) => ({ selectedItemKey }),
        setDisplayMode: (displayMode: DisplayMode) => ({
            displayMode,
        }),
        setActiveTabKey: (activeTabKey: string) => ({ activeTabKey }),
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
            props.initialDisplayMode ?? DisplayMode.PROPERTY_SELECT,
            {
                setDisplayMode: (_, { displayMode }) => displayMode,
            },
        ],
        activeTabKey: [
            null as string | null,
            {
                setActiveTabKey: (_, { activeTabKey }) => activeTabKey,
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
