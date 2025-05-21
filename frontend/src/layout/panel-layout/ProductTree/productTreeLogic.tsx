import { connect, kea, path, selectors } from 'kea'
import { TreeDataItem } from 'lib/lemon-ui/LemonTree/LemonTree'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { getDefaultTreeProducts } from '../ProjectTree/defaultTree'
import { projectTreeLogic } from '../ProjectTree/projectTreeLogic'
import { convertFileSystemEntryToTreeDataItem } from '../ProjectTree/utils'
import type { productTreeLogicType } from './productTreeLogicType'

export const productTreeLogic = kea<productTreeLogicType>([
    path(['layout', 'navigation-3000', 'components', 'productTreeLogic']),
    connect(() => ({
        values: [featureFlagLogic, ['featureFlags'], projectTreeLogic, ['folderStates', 'users']],
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
    }),
])
