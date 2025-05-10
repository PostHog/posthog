import { actions, connect, kea, path, reducers, selectors } from 'kea'
import { TreeDataItem } from 'lib/lemon-ui/LemonTree/LemonTree'
import { getCurrentTeamId } from 'lib/utils/getAppContext'

import { projectTreeLogic } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'
import { convertFileSystemEntryToTreeDataItem, splitPath } from '~/layout/panel-layout/ProjectTree/utils'
import { FileSystemEntry } from '~/queries/schema/schema-general'

import type { shortcutsLogicType } from './shortcutsLogicType'

export const shortcutsLogic = kea<shortcutsLogicType>([
    path(['layout', 'panel-layout', 'Shortcuts', 'shortcutsLogic']),
    connect(() => ({
        actions: [projectTreeLogic, ['updateSyncedFiles', 'deleteTypeAndRef']],
    })),
    actions({
        showModal: true,
        hideModal: true,
        setSelectedItem: (item: TreeDataItem | null) => ({ item }),
        addShortcutItem: (item: FileSystemEntry) => ({ item }),
        deleteShortcut: (item: FileSystemEntry) => ({ item }),
    }),
    reducers({
        shortcutRecords: [
            [] as FileSystemEntry[],
            { persist: true, prefix: `${getCurrentTeamId()}__` },
            {
                addShortcutItem: (state, { item }) => [
                    ...state,
                    // we run this through JSON.parse/JSON.stringify to make sure we don't persist any React classes
                    { ...JSON.parse(JSON.stringify(item)), shortcut: true } as FileSystemEntry,
                ],
                deleteShortcut: (state, { item }) => {
                    return state.filter(
                        (s) =>
                            s.path !== item.path ||
                            s.type !== item.type ||
                            s.href !== item.href ||
                            s.id !== item.id ||
                            s.ref !== item.ref
                    )
                },
                deleteTypeAndRef: (state, { type, ref }) => state.filter((s) => s.type !== type || s.ref !== ref),
                updateSyncedFiles: (state, { files }) => {
                    const filesByTypeAndRef = Object.fromEntries(
                        files.map((file) => [`${file.type}///${file.ref}`, file])
                    )
                    return state.map((item) => {
                        const file = filesByTypeAndRef[`${item.type}///${item.ref}`]
                        if (file) {
                            return { ...item, path: splitPath(file.path).pop() }
                        }
                        return item
                    })
                },
            },
        ],
        selectedItem: [
            null as TreeDataItem | null,
            {
                setSelectedItem: (_, { item }) => item,
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
        shortcuts: [
            (s) => [s.shortcutRecords],
            (shortcutRecords) =>
                convertFileSystemEntryToTreeDataItem({
                    imports: [...shortcutRecords],
                    recent: true,
                    checkedItems: {},
                    folderStates: {},
                    root: 'shortcuts',
                    searchTerm: '',
                }).sort((a, b) => a.name.localeCompare(b.name)),
        ],
    }),
])
