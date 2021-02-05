import { kea } from 'kea'
import { SelectBoxItem, SelectedItem } from 'lib/components/SelectBox'
import { selectBoxLogicType } from './selectBoxLogicType'
import Fuse from 'fuse.js'

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

export const selectBoxLogic = kea<selectBoxLogicType<SelectedItem, SelectBoxItem>>({
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
                setSelectedItem: (_, { item }: { item: SelectedItem | null }) => item,
            },
        ],
        blockMouseOver: [
            false,
            {
                setBlockMouseOver: (_, { block }: { block: boolean }) => block,
            },
        ],
        search: [
            '',
            {
                setSearch: (_, { search }: { search: string }) => search,
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
    }),
    listeners: ({ props, values, actions }) => ({
        clickSelectedItem: ({ item, group }: { item: SelectedItem; group: SelectBoxItem }) => {
            props.updateFilter(group.type, group.getValue(item), group.getLabel(item))
        },
        setBlockMouseOver: ({ block }: { block: boolean }) => {
            if (block) {
                setTimeout(() => actions.setBlockMouseOver(false), 200)
            }
        },
        onKeyDown: ({ e }: { e: React.KeyboardEvent }) => {
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
    }),
})
