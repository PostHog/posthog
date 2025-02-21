import { actions, kea, path, reducers } from 'kea'

import type { playlistLogicType } from './playlistLogicType'

export const playlistLogic = kea<playlistLogicType>([
    path(['lib', 'components', 'playlist', 'playlistLogicType']),
    actions({
        setIsExpanded: (isExpanded: boolean) => ({ isExpanded }),
    }),
    reducers({
        isExpanded: [
            false,
            {
                setIsExpanded: (_, { isExpanded }) => isExpanded,
            },
        ],
    }),
])
