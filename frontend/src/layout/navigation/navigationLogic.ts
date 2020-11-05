import { kea } from 'kea'
import { navigationLogicType } from 'types/layout/navigation/navigationLogicType'

export const navigationLogic = kea<navigationLogicType>({
    actions: {
        setMenuCollapsed: (state) => ({ state }),
    },
    reducers: {
        menuCollapsed: [
            typeof window !== 'undefined' && window.innerWidth <= 991,
            {
                setMenuCollapsed: (_, { state }) => state,
            },
        ],
    },
})
