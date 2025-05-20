import Fuse from 'fuse.js'
import { actions, connect, kea, path, reducers, selectors } from 'kea'
import { TreeDataItem } from 'lib/lemon-ui/LemonTree/LemonTree'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'

import { getDefaultTreeProducts } from '../ProjectTree/defaultTree'
import { convertFileSystemEntryToTreeDataItem } from '../ProjectTree/utils'
import type { productTreeLogicType } from './productTreeLogicType'

export const productTreeLogic = kea<productTreeLogicType>([
    path(['layout', 'navigation-3000', 'components', 'productTreeLogic']),
    connect(() => ({
        values: [featureFlagLogic, ['featureFlags'], projectTreeDataLogic, ['folderStates', 'users']],
        actions: [],
    })),
    actions({
        setSearchTerm: (searchTerm: string) => ({ searchTerm }),
        clearSearch: true,
    }),
    reducers({
        searchTerm: [
            '',
            {
                setSearchTerm: (_, { searchTerm }) => searchTerm,
                clearSearch: () => '',
            },
        ],
    }),
    selectors({
        imports: [
            (s) => [s.featureFlags],
            (featureFlags) =>
                getDefaultTreeProducts().filter((f) => !f.flag || (featureFlags as Record<string, boolean>)[f.flag]),
        ],
        filteredImports: [
            (s) => [s.imports, s.searchTerm],
            (imports, searchTerm) => {
                if (!searchTerm) {
                    return imports
                }
                const fuse = new Fuse(imports, {
                    keys: ['path'],
                    threshold: 0.3,
                })
                const results = fuse.search(searchTerm)
                return results.map((result) => result.item)
            },
        ],
        productTreeItems: [
            (s) => [s.filteredImports, s.folderStates, s.users, s.searchTerm],
            (filteredImports, folderStates, users, searchTerm): TreeDataItem[] =>
                convertFileSystemEntryToTreeDataItem({
                    imports: filteredImports,
                    checkedItems: {},
                    folderStates,
                    root: 'explore',
                    users,
                    searchTerm,
                    foldersFirst: false,
                }),
        ],
    }),
])
