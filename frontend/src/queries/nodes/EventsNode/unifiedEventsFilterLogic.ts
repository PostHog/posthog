import { actions, kea, key, path, props, reducers } from 'kea'

import type { unifiedEventsFilterLogicType } from './unifiedEventsFilterLogicType'

export interface UnifiedEventsFilterLogicProps {
    key: string
}

export const unifiedEventsFilterLogic = kea<unifiedEventsFilterLogicType>([
    path(['queries', 'nodes', 'EventsNode', 'unifiedEventsFilterLogic']),
    props({} as UnifiedEventsFilterLogicProps),
    key((props) => props.key),
    actions({
        setIsOpen: (isOpen: boolean) => ({ isOpen }),
        toggleOpen: true,
    }),
    reducers({
        isOpen: [
            false,
            {
                setIsOpen: (_, { isOpen }) => isOpen,
                toggleOpen: (state) => !state,
            },
        ],
    }),
])
