import { ActivityLogItem } from 'lib/components/ActivityLog/humanizeActivity'

import { APIScopeObject, ActivityScope, CommentType } from '~/types'

/** Allows scenes to set a context which enables richer features of the side panel */
export type SidePanelSceneContext = {
    access_control_resource?: APIScopeObject
    access_control_resource_id?: string
    activity_scope?: ActivityScope | string
    activity_item_id?: ActivityLogItem['item_id']
    // only currently used for comments which are very similar to activity items
    activity_item_context?: CommentType['item_context']
    discussions_disabled?: boolean
}
export const SIDE_PANEL_CONTEXT_KEY = 'sidePanelContext'
