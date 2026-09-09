import type { OrganizationNotificationLockApi } from '~/generated/core/api.schemas'

export const LOCKED_BY_ORGANIZATION = 'An admin of your organization set this for you'

/** Looks up the value an organization enforces for a setting, or null when the choice is the member's. */
export function lockedValueFor(
    locks: OrganizationNotificationLockApi[] | undefined,
    setting: string,
    scopeId: string | number = ''
): boolean | null {
    const match = locks?.find((lock) => lock.setting === setting && lock.scope_id === String(scopeId))
    return match ? match.locked_value : null
}
