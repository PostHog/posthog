import { actions, kea, path, reducers, selectors } from 'kea'

import { IconDatabase, IconHogQL } from '@posthog/icons'

import {
    getDefaultTreeData,
    getDefaultTreeNew,
    getDefaultTreeProducts,
    iconForType,
} from '~/layout/panel-layout/ProjectTree/defaultTree'

import type { newTabSceneLogicType } from './newTabSceneLogicType'

export interface ItemsGridItem {
    category: string
    types: { name: string; icon?: JSX.Element; href?: string }[]
}

export const newTabSceneLogic = kea<newTabSceneLogicType>([
    path(['scenes', 'new-tab', 'newTabSceneLogic']),
    actions({
        setSearch: (search: string) => ({ search }),
    }),
    reducers({
        search: [
            '',
            {
                setSearch: (_, { search }) => search,
            },
        ],
    }),
    selectors({
        itemsGrid: [
            () => [],
            (): ItemsGridItem[] => {
                const newInsightItems = getDefaultTreeNew()
                    .filter(({ path }) => path.startsWith('Insight/'))
                    .map((fs) => ({
                        href: fs.href,
                        name: fs.path.substring(8),
                        icon: iconForType(fs.iconType),
                    }))
                const newDataItems = getDefaultTreeNew()
                    .filter(({ path }) => path.startsWith('Data/'))
                    .map((fs) => ({
                        href: fs.href,
                        name: 'Data ' + fs.path.substring(5).toLowerCase(),
                        icon: iconForType(fs.iconType),
                    }))
                const newOtherItems = getDefaultTreeNew()
                    .filter(({ path }) => !path.startsWith('Insight/') && !path.startsWith('Data/'))
                    .map((fs) => ({
                        href: fs.href,
                        name: fs.path,
                        icon: iconForType(fs.iconType),
                    }))

                const products = getDefaultTreeProducts().map((fs) => ({
                    href: fs.href,
                    name: fs.path,
                    icon: iconForType(fs.iconType),
                }))

                const data = getDefaultTreeData().map((fs) => ({
                    href: fs.href,
                    name: fs.path,
                    icon: iconForType(fs.iconType),
                }))

                const queryTree: ItemsGridItem[] = [
                    {
                        category: 'Create new insight',
                        types: [{ name: 'SQL', icon: <IconDatabase />, href: '/sql' }, ...newInsightItems],
                    },
                    {
                        category: 'Explore products',
                        types: [...products],
                    },
                    {
                        category: 'More things you can create',
                        types: [
                            ...newOtherItems,
                            ...newDataItems,
                            { name: 'Hog program', icon: <IconHogQL />, href: '/debug/hog' },
                        ],
                    },
                    {
                        category: 'Data in or out',
                        types: [...data],
                    },
                ]
                return queryTree
            },
        ],
        filteredItemsGrid: [
            (s) => [s.itemsGrid, s.search],
            (itemsGrid, search): ItemsGridItem[] => {
                if (!search.trim()) {
                    return itemsGrid
                }
                const lowerSearch = search.toLowerCase()
                return itemsGrid
                    .map(({ category, types }) => ({
                        category,
                        types: types.filter((t) => t.name.toLowerCase().includes(lowerSearch)),
                    }))
                    .filter(({ types }) => types.length > 0)
            },
        ],
    }),
])
