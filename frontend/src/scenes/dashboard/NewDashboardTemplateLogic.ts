import { actions, kea, path, reducers } from 'kea'

import type { newDashboardTemplateLogicType } from './NewDashboardTemplateLogicType'

export const newDashboardTemplateLogic = kea<newDashboardTemplateLogicType>([
    path(['scenes', 'dashboard', 'NewDashboardTemplateLogic']),
    actions({
        setDashboardTemplateJSON: (dashboardTemplateJSON: string) => ({ dashboardTemplateJSON }),
        setOpenNewDashboardTemplateModal: (openNewDashboardTemplateModal: boolean) => ({
            openNewDashboardTemplateModal,
        }),
    }),
    reducers({
        dashboardTemplateJSON: [
            '' as string,
            {
                setDashboardTemplateJSON: (_, { dashboardTemplateJSON }) => dashboardTemplateJSON,
            },
        ],
        isOpenNewDashboardTemplateModal: [
            false as boolean,
            {
                setOpenNewDashboardTemplateModal: (_, { openNewDashboardTemplateModal }) =>
                    openNewDashboardTemplateModal,
            },
        ],
    }),
])
