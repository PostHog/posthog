import { kea } from 'kea'
import { AnyPropertyFilter } from '~/types'
import { DisplayMode } from './components/TaxonomicPropertyFilter/TaxonomicPropertyFilter'
import { taxonomicPropertyFilterLogicType } from './taxonomicPropertyFilterLogicType'
import { SelectResultGroup } from './components/TaxonomicPropertyFilter/InfiniteSelectResults'

type GroupMetadataEntry = {
    name: string
    active?: boolean
    count: number | null
}

type GroupMetadata = Record<string, GroupMetadataEntry>

export const taxonomicPropertyFilterLogic = kea<taxonomicPropertyFilterLogicType<GroupMetadata, GroupMetadataEntry>>({
    props: {} as {
        key: string
        onChange?: null | ((filters: AnyPropertyFilter[]) => void)
        initialDisplayMode?: DisplayMode
        groups?: SelectResultGroup[]
    },
    key: (props) => props.key,

    actions: () => ({
        update: true,
        setSearchQuery: (searchQuery: string) => ({ searchQuery }),
        setSelectedItemKey: (selectedItemKey: string | number | null) => ({ selectedItemKey }),
        setDisplayMode: (displayMode: DisplayMode) => ({
            displayMode,
        }),
        setGroupMetadata: (groupMetadata: GroupMetadata) => ({ groupMetadata }),
        setGroupMetadataEntry: (key: string, groupMetadataEntry: Partial<GroupMetadataEntry>) => ({
            key,
            groupMetadataEntry,
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
        groupMetadata: [
            {} as GroupMetadata,
            {
                setGroupMetadata: (_, { groupMetadata }) => groupMetadata,
                setGroupMetadataEntry: (state, { key, groupMetadataEntry }) => ({
                    ...state,
                    [key]: { ...state[key], ...groupMetadataEntry },
                }),
            },
        ],
        activeTabKey: [
            null as string | null,
            {
                setActiveTabKey: (_, { activeTabKey }) => activeTabKey,
            },
        ],
    }),

    events: ({ actions, props }) => ({
        afterMount: () => {
            const metadata: GroupMetadata = {}
            props.groups?.forEach(({ key, name, dataSource }) => {
                metadata[key] = {
                    name,
                    count: dataSource?.length ?? null,
                }
            })
            actions.setGroupMetadata(metadata)
        },
    }),
})
