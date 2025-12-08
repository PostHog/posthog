import { actions, kea, key, path, props, reducers } from 'kea'

import type { actionFilterGroupLogicType } from './actionFilterGroupLogicType'

export interface ActionFilterGroupLogicProps {
    filterUuid: string
}

export const actionFilterGroupLogic = kea<actionFilterGroupLogicType>([
    path(['scenes', 'insights', 'filters', 'ActionFilter', 'ActionFilterGroup', 'actionFilterGroupLogic']),
    props({} as ActionFilterGroupLogicProps),
    key((props) => props.filterUuid),

    actions({
        setHogQLDropdownVisible: (isVisible: boolean) => ({ isVisible }),
    }),

    reducers({
        isHogQLDropdownVisible: [
            false,
            {
                setHogQLDropdownVisible: (_, { isVisible }) => isVisible,
            },
        ],
    }),
])
