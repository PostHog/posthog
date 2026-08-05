import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { FileSystemIconType } from '~/queries/schema/schema-general'
import { APIScopeObject } from '~/types'

/** Resources whose name differs from their icon type in the project tree manifest. */
const SCOPE_TO_ICON_TYPE: Partial<Record<APIScopeObject, FileSystemIconType>> = {
    activity_log: 'activity',
    customer_analytics: 'persons',
    endpoint: 'endpoints',
    external_data_source: 'data_warehouse',
    hog_flow: 'workflows',
    insight: 'insight/trends',
    project: 'home',
    replay_scanner: 'replay_vision',
    session_recording: 'session_replay',
    session_recording_playlist: 'session_replay',
    warehouse_objects: 'data_warehouse',
    warehouse_table: 'data_warehouse',
    warehouse_view: 'data_warehouse',
}

/**
 * Icon for an access-controlled resource, borrowed from the project tree's manifest-driven map so
 * products keep one icon everywhere. Scopes the manifest doesn't know get iconForType's default,
 * so every resource shows an icon.
 */
export function ScopeIcon({ scope }: { scope: APIScopeObject }): JSX.Element {
    return iconForType(SCOPE_TO_ICON_TYPE[scope] ?? (scope as FileSystemIconType))
}
