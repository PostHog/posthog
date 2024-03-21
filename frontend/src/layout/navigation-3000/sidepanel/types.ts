import { ActivityLogItem } from 'lib/components/ActivityLog/humanizeActivity'

import { ActivityScope } from '~/types'

/** Allows scenes to set a context which enables richer features of the side panel */
export type SidePanelSceneContext = {
    activity_scope?: ActivityScope
    activity_item_id?: ActivityLogItem['item_id']
}
export const SIDE_PANEL_CONTEXT_KEY = 'sidePanelContext'
