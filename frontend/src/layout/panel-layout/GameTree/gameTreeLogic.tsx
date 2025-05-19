import { connect, kea, path, selectors } from 'kea'
import { TreeDataItem } from 'lib/lemon-ui/LemonTree/LemonTree'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { getDefaultTreeGames } from '../ProjectTree/defaultTree'
import { projectTreeLogic } from '../ProjectTree/projectTreeLogic'
import { convertFileSystemEntryToTreeDataItem } from '../ProjectTree/utils'
import type { gameTreeLogicType } from './gameTreeLogicType'

export const gameTreeLogic = kea<gameTreeLogicType>([
    path(['layout', 'navigation-3000', 'components', 'gameTreeLogic']),
    connect(() => ({
        values: [featureFlagLogic, ['featureFlags'], projectTreeLogic, ['folderStates', 'users']],
        actions: [],
    })),
    selectors({
        gameTreeItems: [
            (s) => [s.featureFlags, s.folderStates, s.users],
            (featureFlags, folderStates, users): TreeDataItem[] =>
                convertFileSystemEntryToTreeDataItem({
                    imports: getDefaultTreeGames().filter(
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
