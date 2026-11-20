import { combineUrl, router } from 'kea-router'

import { LemonDialog } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

export function confirmDeleteRole(isDefaultRole: boolean, onConfirm: () => void): void {
    const baseContent = 'Are you sure you want to delete this role? This action cannot be undone.'

    LemonDialog.open({
        title: 'Delete role',
        maxWidth: 400,
        content: (
            <div>
                <p>{baseContent}</p>
                {isDefaultRole && (
                    <p className="text-warning font-medium mt-2">
                        ⚠️ This role is currently set as the default for new members and will be cleared from
                        organization settings.
                    </p>
                )}
            </div>
        ),
        primaryButton: {
            children: 'Delete permanently',
            onClick: onConfirm,
            status: 'danger',
        },
        secondaryButton: {
            children: 'Cancel',
        },
    })
}

export function openRoleAccessSettings(roleId: string): void {
    router.actions.push(
        combineUrl(urls.settings('environment-access-control'), {
            access_tab: 'roles',
            access_role_id: roleId,
        }).url
    )
}
