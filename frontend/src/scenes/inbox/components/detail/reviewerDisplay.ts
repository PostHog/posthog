import { EnrichedReviewer } from '../../types'

/** A reviewer that can be added to a report, resolved from org members with a GitHub identity. */
export interface AvailableReviewerOption {
    user_uuid: string
    name: string
    email: string
}

/** Current user fields needed to pin / label the "Me" entry. Mirrors desktop `CurrentSuggestedReviewerUser`. */
export interface CurrentReviewerUser {
    uuid: string
    first_name?: string | null
    last_name?: string | null
    email?: string | null
}

function normalizeString(value: string | null | undefined): string {
    return typeof value === 'string' ? value.trim() : ''
}

function buildCurrentUserName(currentUser?: CurrentReviewerUser | null): string {
    const firstName = normalizeString(currentUser?.first_name)
    const lastName = normalizeString(currentUser?.last_name)
    return [firstName, lastName].filter(Boolean).join(' ')
}

/**
 * Build the add-reviewer option list: pin the current user ("Me") first, then the rest sorted by name.
 * Mirrors desktop `buildSuggestedReviewerFilterOptions`.
 */
export function buildAddReviewerOptions(
    available: AvailableReviewerOption[],
    currentUser?: CurrentReviewerUser | null
): AvailableReviewerOption[] {
    const byUuid = new Map<string, AvailableReviewerOption>()
    for (const reviewer of available) {
        const uuid = normalizeString(reviewer.user_uuid)
        if (!uuid || byUuid.has(uuid)) {
            continue
        }
        byUuid.set(uuid, {
            user_uuid: uuid,
            name: normalizeString(reviewer.name),
            email: normalizeString(reviewer.email),
        })
    }

    const currentUserUuid = normalizeString(currentUser?.uuid)
    let meOption: AvailableReviewerOption | null = null
    if (currentUserUuid) {
        const existing = byUuid.get(currentUserUuid)
        meOption = {
            user_uuid: currentUserUuid,
            name: buildCurrentUserName(currentUser) || existing?.name || '',
            email: normalizeString(currentUser?.email) || existing?.email || '',
        }
        byUuid.set(currentUserUuid, meOption)
    }

    const others = Array.from(byUuid.values())
        .filter((option) => option.user_uuid !== currentUserUuid)
        .sort(
            (a, b) =>
                a.name.toLowerCase().localeCompare(b.name.toLowerCase()) ||
                a.email.toLowerCase().localeCompare(b.email.toLowerCase()) ||
                a.user_uuid.localeCompare(b.user_uuid)
        )

    return meOption ? [meOption, ...others] : others
}

/** Display name for an add-reviewer option, with a "(Me)" suffix when it's the current user. */
export function getReviewerOptionDisplayName(option: AvailableReviewerOption, isMe: boolean): string {
    const base = normalizeString(option.name) || normalizeString(option.email) || 'Unknown user'
    return isMe ? `${base} (Me)` : base
}

/** Does an existing reviewer match an available option? Match by user uuid. */
export function reviewerMatchesOption(reviewer: EnrichedReviewer, option: AvailableReviewerOption): boolean {
    return !!reviewer.user?.uuid && reviewer.user.uuid === option.user_uuid
}

/** Convert reviewers to the write-content entries the backend expects (`{ user_uuid }` / `{ github_login }`). */
export function reviewersToWriteContent(reviewers: EnrichedReviewer[]): Record<string, string>[] {
    return reviewers
        .map((reviewer): Record<string, string> | null => {
            if (reviewer.user?.uuid) {
                return { user_uuid: reviewer.user.uuid }
            }
            if (reviewer.github_login) {
                return { github_login: reviewer.github_login }
            }
            return null
        })
        .filter((entry): entry is Record<string, string> => entry !== null)
}
