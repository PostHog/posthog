import type { UserType } from '~/types'

// Mirrors `IsStaffUserOrImpersonating` on the organization-members endpoint the Users tab reads,
// so a viewer who cannot read it never sees the tab or triggers the request.
export function canViewAccountRelatedUsers(user: UserType | null): boolean {
    return !!user && (user.is_staff || user.is_impersonated)
}
