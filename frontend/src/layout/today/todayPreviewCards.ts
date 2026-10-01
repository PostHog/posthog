import { ChannelDTOApi, PrStateEnumApi, TaskUserBasicInfoApi } from 'products/tasks/frontend/generated/api.schemas'
import { SpacePresence } from 'products/tasks/frontend/spaces/spacePresence'
import { TaskPullRequest } from 'products/tasks/frontend/spaces/taskPullRequests'

import { TodaySessionDot, todaySessionDot } from './todaySessionDot'
import { TodayWorkItem } from './todayWorkItems'

/** Repositories past this are counted rather than named, so the card stays a glance. */
const SPACE_PREVIEW_REPOSITORY_LIMIT = 3

export type TodaySpaceKind = 'public' | 'private' | 'personal'

/** What a session row's hover card says, built once per row so the shared card gets a stable payload. */
export interface TodaySessionPreview {
    kind: 'session'
    title: string
    dot: TodaySessionDot
    pinned: boolean
    pullRequest: TaskPullRequest | null
    pullRequestState: PrStateEnumApi | null
    spaceName: string | null
    repository: string | null
    author: TaskUserBasicInfoApi | null
    timestamp: string | null
    message: string | null
}

/** What a space row's hover card says. */
export interface TodaySpacePreview {
    kind: 'space'
    name: string
    spaceKind: TodaySpaceKind
    /** The creator first, then whoever worked in the space most recently. */
    people: TaskUserBasicInfoApi[]
    liveUuids: string[]
    creatorUuid: string | null
    lastActivityAt: string | null
    repositories: string[]
    hiddenRepositoryCount: number
}

export type TodayPreviewPayload = TodaySessionPreview | TodaySpacePreview

export function spaceKind(space: Pick<ChannelDTOApi, 'channel_type' | 'system_role'>): TodaySpaceKind {
    if (space.system_role === 'personal' || space.channel_type === 'personal') {
        return 'personal'
    }
    return space.channel_type === 'private' ? 'private' : 'public'
}

export function sessionPreview(
    item: TodayWorkItem,
    {
        unread,
        pinned,
        pullRequestStates,
        spaceNames,
    }: {
        unread: boolean
        pinned: boolean
        pullRequestStates: Record<string, PrStateEnumApi>
        spaceNames: Record<string, string>
    }
): TodaySessionPreview {
    // The row shows only the first pull request, so the card names the same one.
    const [pullRequest] = item.pullRequests
    return {
        kind: 'session',
        title: item.title || 'Untitled session',
        dot: todaySessionDot(item, unread),
        pinned,
        pullRequest: pullRequest ?? null,
        pullRequestState: pullRequest ? (pullRequestStates[pullRequest.url] ?? null) : null,
        spaceName: item.channel ? (spaceNames[item.channel] ?? null) : null,
        repository: item.repository,
        author: item.author,
        timestamp: item.timestamp,
        message: item.finalMessage,
    }
}

/**
 * The creator leads whether or not they worked here lately, so the crown always sits on the first face.
 * They are not listed twice when they are also in the recent people.
 */
function spacePeople(
    creator: TaskUserBasicInfoApi | null | undefined,
    presence: SpacePresence | undefined
): TaskUserBasicInfoApi[] {
    const people = creator ? [creator] : []
    for (const person of presence?.people ?? []) {
        if (!people.some((existing) => existing.uuid === person.uuid)) {
            people.push(person)
        }
    }
    return people
}

export function spacePreview(
    space: ChannelDTOApi,
    name: string,
    presence: SpacePresence | undefined,
    lastActivityAt: string | undefined
): TodaySpacePreview {
    return {
        kind: 'space',
        name,
        spaceKind: spaceKind(space),
        people: spacePeople(space.created_by, presence),
        liveUuids: presence?.liveUuids ?? [],
        creatorUuid: space.created_by?.uuid ?? null,
        lastActivityAt: lastActivityAt ?? null,
        repositories: space.repositories.slice(0, SPACE_PREVIEW_REPOSITORY_LIMIT),
        hiddenRepositoryCount: Math.max(0, space.repositories.length - SPACE_PREVIEW_REPOSITORY_LIMIT),
    }
}
