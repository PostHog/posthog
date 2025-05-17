import { connect, kea, path, selectors } from 'kea'
import { TreeDataItem } from 'lib/lemon-ui/LemonTree/LemonTree'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { panelLayoutLogic } from '../panelLayoutLogic'
import { getDefaultTreeProducts } from '../ProjectTree/defaultTree'
import { projectTreeLogic } from '../ProjectTree/projectTreeLogic'
import { convertFileSystemEntryToTreeDataItem } from '../ProjectTree/utils'
import type { productTreeLogicType } from './productTreeLogicType'

export const productTreeLogic = kea<productTreeLogicType>([
    path(['layout', 'navigation-3000', 'components', 'productTreeLogic']),
    connect(() => ({
        values: [
            featureFlagLogic,
            ['featureFlags'],
            projectTreeLogic,
            ['folderStates', 'users'],
            panelLayoutLogic,
            ['searchTerm'],
        ],
        actions: [],
    })),
    selectors({
        productTreeItems: [
            (s) => [s.featureFlags, s.folderStates, s.users],
            (featureFlags, folderStates, users): TreeDataItem[] =>
                convertFileSystemEntryToTreeDataItem({
                    imports: getDefaultTreeProducts().filter(
                        (f) => !f.flag || (featureFlags as Record<string, boolean>)[f.flag]
                    ),
                    checkedItems: {},
                    folderStates,
                    root: 'explore',
                    users,
                    foldersFirst: false,
                }),
        ],
        searchResults: [
            (s) => [s.searchTerm, s.productTreeItems],
            (searchTerm, productTreeItems): TreeDataItem[] => {
                return productTreeItems.filter((item) => item.name.toLowerCase().includes(searchTerm.toLowerCase()))
            },
        ],
    }),
])
