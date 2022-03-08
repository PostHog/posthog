import { kea } from 'kea'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { teamLogic } from 'scenes/teamLogic'
import { projectHomepageLogicType } from './projectHomepageLogicType'

export const projectHomepageLogic = kea<projectHomepageLogicType>({
    path: ['scenes', 'project-homepage', 'projectHomepageLogic'],
    connect: {
        values: [
            teamLogic,
            ['currentTeam'],
            dashboardLogic({ id: teamLogic.values.currentTeam?.primary_dashboard }),
            ['dashboard'],
        ],
    },
})
