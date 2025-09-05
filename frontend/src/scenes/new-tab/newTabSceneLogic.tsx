import { connect, kea, key, listeners, path, props, selectors } from 'kea'
import { router } from 'kea-router'

import { IconDatabase, IconHogQL } from '@posthog/icons'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import {
    ProductIconWrapper,
    getDefaultTreeData,
    getDefaultTreeNew,
    getDefaultTreeProducts,
    iconForType,
} from '~/layout/panel-layout/ProjectTree/defaultTree'
import { FileSystemImport } from '~/queries/schema/schema-general'

import type { newTabSceneLogicType } from './newTabSceneLogicType'

export interface ItemsGridItem {
    category: string
    types: { name: string; icon?: JSX.Element; href?: string; filters?: string[]; flag?: string }[]
}

export interface ItemsGridItemSingle {
    category: string
    type: { name: string; icon?: JSX.Element; href?: string }
}

function getIconForFileSystemItem(fs: FileSystemImport): JSX.Element {
    // If the item has a direct icon property, use it with color wrapper
    if ('icon' in fs && fs.icon) {
        return (
            <ProductIconWrapper type={fs.type} colorOverride={fs.iconColor}>
                {fs.icon}
            </ProductIconWrapper>
        )
    }

    // Fall back to iconForType for iconType or type
    return iconForType('iconType' in fs ? fs.iconType : fs.type, fs.iconColor)
}

export const newTabSceneLogic = kea<newTabSceneLogicType>([
    path(['scenes', 'new-tab', 'newTabSceneLogic']),
    props({} as { tabId?: string }),
    connect(() => ({
        values: [featureFlagLogic, ['featureFlags']],
    })),
    key((props) => props.tabId || 'default'),
    selectors({
        itemsGrid: [
            (s) => [s.featureFlags],
            (featureFlags): ItemsGridItem[] => {
                const newInsightItems = getDefaultTreeNew()
                    .filter(({ path }) => path.startsWith('Insight/'))
                    .map((fs) => ({
                        href: fs.href,
                        name: 'new ' + fs.path.substring(8),
                        icon: getIconForFileSystemItem(fs),
                        filters: ['new', 'insight'],
                        flag: fs.flag,
                    }))
                    .filter(({ flag }) => !flag || featureFlags[flag as keyof typeof featureFlags])
                const newDataItems = getDefaultTreeNew()
                    .filter(({ path }) => path.startsWith('Data/'))
                    .map((fs) => ({
                        href: fs.href,
                        name: 'Data ' + fs.path.substring(5).toLowerCase(),
                        icon: getIconForFileSystemItem(fs),
                        filters: ['new', 'data'],
                        flag: fs.flag,
                    }))
                    .filter(({ flag }) => !flag || featureFlags[flag as keyof typeof featureFlags])
                const newOtherItems = getDefaultTreeNew()
                    .filter(({ path }) => !path.startsWith('Insight/') && !path.startsWith('Data/'))
                    .map((fs) => ({
                        href: fs.href,
                        name: 'new ' + fs.path,
                        icon: getIconForFileSystemItem(fs),
                        filters: ['new'],
                        flag: fs.flag,
                    }))
                    .filter(({ flag }) => !flag || featureFlags[flag as keyof typeof featureFlags])

                const products = getDefaultTreeProducts()
                    .map((fs) => ({
                        href: fs.href,
                        name: fs.path,
                        icon: getIconForFileSystemItem(fs),
                        filters: ['app'],
                        flag: fs.flag,
                    }))
                    .filter(({ flag }) => !flag || featureFlags[flag as keyof typeof featureFlags])

                const data = getDefaultTreeData()
                    .map((fs) => ({
                        href: fs.href,
                        name: fs.path,
                        icon: getIconForFileSystemItem(fs),
                        flag: fs.flag,
                    }))
                    .filter(({ flag }) => !flag || featureFlags[flag as keyof typeof featureFlags])

                const queryTree: ItemsGridItem[] = [
                    {
                        category: 'apps',
                        types: [...products.sort((a, b) => a.name.localeCompare(b.name))],
                    },
                    {
                        category: 'new',
                        types: [
                            ...newOtherItems.sort((a, b) => a.name.localeCompare(b.name)),
                            ...newDataItems.sort((a, b) => a.name.localeCompare(b.name)),
                            { name: 'Hog program', icon: <IconHogQL />, href: '/debug/hog', filters: ['hog'] },
                            { name: 'SQL', icon: <IconDatabase />, href: '/sql', filters: ['sql'] },
                            ...newInsightItems,
                        ],
                    },
                    {
                        category: 'data',
                        types: [...data.sort((a, b) => a.name.localeCompare(b.name))],
                    },
                ]
                return queryTree
            },
        ],
    }),
    listeners(({ values }) => ({
        onSubmit: () => {
            if (values.selectedItem?.type?.href) {
                router.actions.push(values.selectedItem.type.href)
            }
        },
    })),
])
