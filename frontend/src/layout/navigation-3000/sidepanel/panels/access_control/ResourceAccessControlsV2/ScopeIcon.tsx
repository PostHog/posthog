import {
    IconDownload,
    IconList,
    IconLlmPromptManagement,
    IconMCP,
    IconPlaylist,
    IconScatter,
    IconShare,
    IconSupport,
    IconToolbar,
} from '@posthog/icons'

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

/** Resources with no project tree icon type to borrow, kept explicit. */
const SCOPE_ICON_OVERRIDES: Partial<Record<APIScopeObject, JSX.Element>> = {
    ai_observability_clusters: <IconScatter />,
    export: <IconDownload />,
    llm_playground: <IconPlaylist />,
    llm_skill: <IconLlmPromptManagement />,
    mcp_analytics: <IconMCP />,
    sharing_configuration: <IconShare />,
    tagger: <IconList />,
    ticket: <IconSupport />,
    toolbar: <IconToolbar />,
}

/**
 * Icon for an access-controlled resource, borrowed from the project tree's manifest-driven map so
 * products keep one icon everywhere. iconForType has its own default, so every scope gets an icon.
 */
export function ScopeIcon({ scope }: { scope: APIScopeObject }): JSX.Element {
    return SCOPE_ICON_OVERRIDES[scope] ?? iconForType(SCOPE_TO_ICON_TYPE[scope] ?? (scope as FileSystemIconType))
}
