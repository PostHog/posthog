import { kea } from 'kea'
import { SelectBoxItem, SelectedItem } from 'lib/components/SelectBox'
import { selectBoxLogicType } from './selectBoxLogicType'
import Fuse from 'fuse.js'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

const scrollUpIntoView = (key: string): void => {
    const searchList = document.querySelector('.search-list')
    const item = document.querySelector('.search-list [datakey="' + key + '"]')
    if (!item || !searchList) {
        return
    }
    const diff = item.getBoundingClientRect().top - searchList.getBoundingClientRect().top
    if (diff - 30 < 0) {
        searchList.scrollTop = searchList.scrollTop + diff - 30
    }
}
const scrollDownIntoView = (key: string): void => {
    const searchList = document.querySelector('.search-list')
    const item = document.querySelector('.search-list [datakey="' + key + '"]')
    if (!item || !searchList) {
        return
    }
    const diff = item.getBoundingClientRect().top - searchList.getBoundingClientRect().bottom
    if (diff + 30 > 0) {
        searchList.scrollTop = searchList.scrollTop + diff + 30
    }
}

export const searchItems = (sources: SelectedItem[], search: string): SelectedItem[] => {
    return new Fuse(sources, {
        keys: ['name'],
        threshold: 0.3,
    })
        .search(search)
        .map((result) => result.item)
}

export const selectBoxLogic = kea<selectBoxLogicType>({
    path: ['lib', 'logic', 'selectBoxLogic'],
    props: {} as {
        items: SelectBoxItem[]
        updateFilter: (type: any, id: string | number, name: string) => void
    },
    actions: {
        setSelectedItem: (item: SelectedItem | null) => ({ item }),
        setSearch: (search: string) => ({ search }),
        clickSelectedItem: (item: SelectedItem, group: SelectBoxItem) => ({ item, group }),
        setBlockMouseOver: (block: boolean) => ({ block }),
        onKeyDown: (e) => ({ e }),
    },
    reducers: {
        selectedItem: [
            null as SelectedItem | null,
            {
                setSelectedItem: (_, { item }) => item,
            },
        ],
        blockMouseOver: [
            false,
            {
                setBlockMouseOver: (_, { block }) => block,
            },
        ],
        search: [
            '',
            {
                setSearch: (_, { search }) => search,
            },
        ],
    },
    selectors: ({ selectors, props }) => ({
        selectedGroup: [
            () => [selectors.selectedItem],
            (item: SelectedItem | null): SelectBoxItem | null => {
                if (!item) {
                    return null
                }
                return (
                    props.items.filter(
                        (boxItem) => boxItem.dataSource.filter((i) => i.key === item.key).length > 0
                    )[0] || null
                )
            },
        ],
        data: [
            (s) => [s.search],
            (search): SelectBoxItem[] => {
                if (!search) {
                    return props.items
                }
                const newItems: SelectBoxItem[] = []
                for (const item of props.items) {
                    newItems.push({
                        ...item,
                        dataSource: searchItems(item.dataSource, search),
                        metadata: { search },
                    })
                }
                return newItems
            },
        ],
    }),
    listeners: ({ props, values, actions }) => ({
        clickSelectedItem: ({ item, group }: { item: SelectedItem; group: SelectBoxItem }) => {
            if (item.onSelect) {
                item.onSelect({ item, group })
                if (item.onSelectPreventDefault) {
                    return
                }
            }
            props.updateFilter(group.type, group.getValue(item), group.getLabel(item))
        },
        setBlockMouseOver: ({ block }: { block: boolean }) => {
            if (block) {
                setTimeout(() => actions.setBlockMouseOver(false), 200)
            }
        },
        onKeyDown: async (
            {
                e,
            }: {
                e: React.KeyboardEvent
            },
            breakpoint
        ) => {
            await breakpoint(100) // debounce for 100ms
            let allSources = props.items.map((item) => item.dataSource).flat()
            allSources = !values.search ? allSources : searchItems(allSources, values.search)
            const currentIndex =
                allSources.findIndex((item: SelectedItem) => item.key === values.selectedItem?.key) || 0

            if (e.key === 'ArrowDown') {
                const item = allSources[currentIndex + 1]
                if (item) {
                    actions.setSelectedItem(item)
                    scrollDownIntoView(item.key)
                    actions.setBlockMouseOver(true)
                }
            } else if (e.key === 'ArrowUp') {
                const item = allSources[currentIndex - 1]
                if (item) {
                    actions.setSelectedItem(item)
                    scrollUpIntoView(item.key)
                    actions.setBlockMouseOver(true)
                }
            } else if (e.key === 'Enter' && values.selectedItem && values.selectedGroup) {
                actions.clickSelectedItem(values.selectedItem, values.selectedGroup)
            } else {
                return
            }
            e.stopPropagation()
            e.preventDefault()
        },
        setSearch: async ({ search }, breakpoint) => {
            await breakpoint(700)
            if (values.data[0].metadata?.search === search) {
                const extraProps = {} as Record<string, number>
                for (const item of values.data) {
                    extraProps[`count_${item.key}`] = item.dataSource.length
                    if (item.key === 'events') {
                        extraProps.count_posthog_events = item.dataSource.filter(({ name }) => name[0] === '$').length
                    }
                }
                eventUsageLogic.actions.reportEventSearched(search, extraProps)
            }
        },
    }),
})
