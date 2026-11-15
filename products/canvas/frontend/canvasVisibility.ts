import type { CanvasSpace } from './canvasTasksApi'

export type CanvasVisibility = 'private' | 'public' | 'shared'

type SpaceShape = Pick<CanvasSpace, 'system_role' | 'channel_type'>

export function canvasVisibility(space: SpaceShape): CanvasVisibility {
    if (space.system_role === 'personal' || space.channel_type === 'personal') {
        return 'private'
    }
    return space.channel_type === 'private' ? 'shared' : 'public'
}

export function visibilitySpace<T extends Pick<CanvasSpace, 'system_role'>>(
    spaces: T[],
    visibility: 'private' | 'public'
): T | null {
    const role = visibility === 'private' ? 'personal' : 'general'
    return spaces.find((space) => space.system_role === role) ?? null
}
