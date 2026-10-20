import { dayjs } from 'lib/dayjs'
import { fullNameOrEmail } from 'lib/utils/strings'

import type { BuildStatusEnumApi, CanvasDraftApi, CanvasVersionApi } from '../generated/api.schemas'

/** What a version changed, in words: the prompt it was published with, else what kind of change it was. */
export function canvasVersionTitle(version: Pick<CanvasVersionApi, 'prompt' | 'parent_version_id'>): string {
    const prompt = version.prompt?.trim()
    if (prompt) {
        return prompt
    }
    return version.parent_version_id ? 'Published a change' : 'Created the canvas'
}

/** Who published a version and when, for example "Published by Ada · 2 hours ago". */
export function canvasVersionByline(version: Pick<CanvasVersionApi, 'task_id' | 'created_by' | 'created_at'>): string {
    const age = dayjs(version.created_at).fromNow()
    if (version.task_id) {
        return `Published by an agent · ${age}`
    }
    return version.created_by ? `Published by ${fullNameOrEmail(version.created_by)} · ${age}` : `Published ${age}`
}

/** Who staged a draft and when. A draft without a person was staged by an agent. */
export function canvasDraftByline(draft: Pick<CanvasDraftApi, 'created_by' | 'created_at'>): string {
    const age = dayjs(draft.created_at).fromNow()
    return draft.created_by ? `Staged by ${fullNameOrEmail(draft.created_by)} · ${age}` : `Staged by an agent · ${age}`
}

export function canvasDraftTitle(draft: Pick<CanvasDraftApi, 'prompt'>): string {
    return draft.prompt?.trim() || 'Untitled draft'
}

const BUILD_STATUS_LABELS: Record<BuildStatusEnumApi, string> = {
    queued: 'Queued',
    building: 'Building',
    ready: 'Built',
    failed: 'Build failed',
}

export function canvasBuildStatusLabel(status: BuildStatusEnumApi | null): string {
    return status ? BUILD_STATUS_LABELS[status] : 'Not built'
}

export function canvasBuildStatusBadgeVariant(
    status: BuildStatusEnumApi | null
): 'default' | 'info' | 'success' | 'destructive' {
    if (status === 'ready') {
        return 'success'
    }
    if (status === 'failed') {
        return 'destructive'
    }
    return status ? 'info' : 'default'
}
