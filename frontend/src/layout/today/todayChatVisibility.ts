import { ChannelDTOApi } from 'products/tasks/frontend/generated/api.schemas'

export type TodayChatVisibility = 'personal' | 'public' | 'shared'

type SpaceShape = Pick<ChannelDTOApi, 'id' | 'channel_type' | 'system_role'>

type NamedSpaceShape = SpaceShape & Pick<ChannelDTOApi, 'name'>

export function personalSpace<T extends SpaceShape>(spaces: T[]): T | null {
    return spaces.find((space) => space.system_role === 'personal') ?? null
}

export function publicSpace<T extends SpaceShape>(spaces: T[]): T | null {
    return spaces.find((space) => space.system_role === 'general') ?? null
}

export function chatVisibility(spaceId: string | null, spaces: SpaceShape[]): TodayChatVisibility {
    if (!spaceId || spaces.length === 0) {
        return 'personal'
    }
    const space = spaces.find((candidate) => candidate.id === spaceId)
    if (!space) {
        return 'shared'
    }
    if (space.system_role === 'personal' || space.channel_type === 'personal') {
        return 'personal'
    }
    return space.channel_type === 'private' ? 'shared' : 'public'
}

export function chatVisibilityLabel(spaceId: string | null, spaces: NamedSpaceShape[]): string {
    const visibility = chatVisibility(spaceId, spaces)
    if (visibility === 'personal') {
        return 'Personal'
    }
    if (visibility === 'public') {
        return 'Public'
    }
    const space = spaces.find((candidate) => candidate.id === spaceId)
    return space ? `Shared · ${space.name}` : 'Shared'
}
