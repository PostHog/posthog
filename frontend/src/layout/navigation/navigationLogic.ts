import { kea } from 'kea'
import { navigationLogicType } from 'types/layout/navigation/navigationLogicType'

export const navigationLogic = kea<navigationLogicType>({
    actions: {
        setMenuCollapsed: (collapsed) => ({ collapsed }),
        collapseMenu: () => {},
    },
    reducers: {
        menuCollapsed: [
            typeof window !== 'undefined' && window.innerWidth <= 991,
            {
                setMenuCollapsed: (_, { collapsed }) => collapsed,
            },
        ],
    },
    listeners: ({ values, actions }) => ({
        collapseMenu: () => {
            if (!values.menuCollapsed && window.innerWidth <= 991) {
                actions.setMenuCollapsed(true)
            }
        },
    }),
})
