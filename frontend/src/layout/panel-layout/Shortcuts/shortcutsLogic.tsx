import { actions, afterMount, connect, kea, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { TreeDataItem } from 'lib/lemon-ui/LemonTree/LemonTree'

import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'
import { convertFileSystemEntryToTreeDataItem, escapePath, splitPath } from '~/layout/panel-layout/ProjectTree/utils'
import { FileSystemEntry } from '~/queries/schema/schema-general'

import type { shortcutsLogicType } from './shortcutsLogicType'

export const shortcutsLogic = kea<shortcutsLogicType>([
    path(['layout', 'panel-layout', 'Shortcuts', 'shortcutsLogic']),
    connect(() => ({
        actions: [projectTreeDataLogic, ['addLoadedResults', 'deleteTypeAndRef']],
    })),
    actions({
        showModal: true,
        hideModal: true,
        setSelectedItem: (id: TreeDataItem['id']) => ({ id }),
        addShortcutItem: (item: FileSystemEntry) => ({ item }),
        deleteShortcut: (id: FileSystemEntry['id']) => ({ id }),
        loadShortcuts: true,
    }),
    loaders(({ values }) => ({
        shortcutData: [
            [] as FileSystemEntry[],
            {
                loadShortcuts: async () => {
                    const response = await api.fileSystemShortcuts.list()
                    return response.results
                },
                addShortcutItem: async ({ item }) => {
                    const response = await api.fileSystemShortcuts.create({
                        path: splitPath(item.path).pop() ?? 'Unnamed',
                        type: item.type,
                        ref: item.ref,
                        href: item.href,
                    })
                    return [...values.shortcutData, response]
                },
                deleteShortcut: async ({ id }) => {
                    await api.fileSystemShortcuts.delete(id)
                    return values.shortcutData.filter((s) => s.id !== id)
                },
            },
        ],
    })),
    reducers({
        shortcutData: [
            [] as FileSystemEntry[],
            {
                deleteTypeAndRef: (state, { type, ref }) => state.filter((s) => s.type !== type || s.ref !== ref),
                addLoadedResults: (state, { results }) => {
                    const filesByTypeAndRef = Object.fromEntries(
                        results.results.map((file) => [`${file.type}//${file.ref}`, file])
                    )
                    return state.map((item) => {
                        const file = filesByTypeAndRef[`${item.type}//${item.ref}`]
                        if (file) {
                            return { ...item, path: escapePath(splitPath(file.path).pop() ?? 'Unnamed') }
                        }
                        return item
                    })
                },
            },
        ],
        selectedItemId: [
            null as TreeDataItem['id'] | null,
            {
                setSelectedItem: (_, { id }) => id,
            },
        ],
        modalVisible: [
            false,
            {
                showModal: () => true,
                hideModal: () => false,
                addShortcutItem: () => false,
            },
        ],
    }),
    selectors({
        selectedItem: [
            (s) => [s.selectedItemId, s.shortcutData],
            (selectedItemId, shortcutData) =>
                selectedItemId ? shortcutData.find((item) => item.id === selectedItemId) : null,
        ],
        shortcuts: [
            (s) => [s.shortcutData],
            (shortcutData) =>
                convertFileSystemEntryToTreeDataItem({
                    imports: [...shortcutData],
                    recent: true,
                    checkedItems: {},
                    folderStates: {},
                    root: 'shortcuts',
                    searchTerm: '',
                    allShortcuts: true,
                }).sort((a, b) => a.name.localeCompare(b.name)),
        ],
        shortcutsLoading: [(s) => [s.shortcutDataLoading], (loading) => loading],
    }),
    afterMount(({ actions }) => {
        actions.loadShortcuts()
    }),
])
