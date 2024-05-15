import { kea, path } from 'kea'

import type { eventsManagementSidebarLogicType } from './eventsManagementType'

export const eventsManagementSidebarLogic = kea<eventsManagementSidebarLogicType>([
    path(['layout', 'navigation-3000', 'sidebars', 'eventsManagementSidebarLogic']),
])
