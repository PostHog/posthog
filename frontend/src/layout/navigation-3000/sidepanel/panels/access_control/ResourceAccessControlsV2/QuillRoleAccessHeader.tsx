import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useState } from 'react'

import { IconEllipsis, IconGear, IconPeople, IconTrash } from '@posthog/icons'
import {
    AlertDialog,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
    Text,
} from '@posthog/quill'

import { organizationLogic } from 'scenes/organizationLogic'
import { urls } from 'scenes/urls'

import { roleAccessControlLogic } from '../roleAccessControlLogic'
import { accessControlsLogic } from './accessControlsLogic'
import { roleMemberNames } from './helpers'
import type { AccessControlRoleEntry } from './types'

export function QuillRoleAccessHeader({
    projectId,
    role,
}: {
    projectId: string
    role: AccessControlRoleEntry
}): JSX.Element {
    const { sortedRoles } = useValues(roleAccessControlLogic)
    const { isAdminOrOwner } = useValues(organizationLogic)
    const { deleteRole } = useActions(roleAccessControlLogic)
    const { closeAccessDetailDialog } = useActions(accessControlsLogic({ projectId }))
    const [confirmOpen, setConfirmOpen] = useState(false)

    const members = sortedRoles.find((r) => r.id === role.role_id)?.members ?? []

    return (
        <div className="flex items-center justify-between gap-2">
            <div className="flex min-w-0 items-center gap-2">
                <span className="flex items-center text-muted-foreground">
                    <IconPeople />
                </span>
                <Text size="sm" weight="medium" render={<span className="truncate" />}>
                    {role.role_name}
                </Text>
            </div>
            <DropdownMenu>
                <DropdownMenuTrigger render={<Button size="icon" aria-label="Role actions" tooltip="Role actions" />}>
                    <IconEllipsis />
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                    <DropdownMenuItem onClick={() => router.actions.push(urls.settings('organization-roles'))}>
                        <IconGear />
                        Manage roles
                    </DropdownMenuItem>
                    <DropdownMenuItem
                        variant="destructive"
                        disabledReason={!isAdminOrOwner ? 'Only organization admins can change roles' : undefined}
                        onClick={() => setConfirmOpen(true)}
                    >
                        <IconTrash />
                        Delete role
                    </DropdownMenuItem>
                </DropdownMenuContent>
            </DropdownMenu>
            <AlertDialog open={confirmOpen} onOpenChange={setConfirmOpen}>
                <AlertDialogContent>
                    <AlertDialogHeader>
                        <AlertDialogTitle>Delete the {role.role_name} role?</AlertDialogTitle>
                        <AlertDialogDescription>
                            This removes every access rule the role grants, in this project and in every other project
                            in the organization.
                        </AlertDialogDescription>
                        {members.length > 0 && (
                            <AlertDialogDescription>
                                {members.length === 1 ? '1 member loses' : `${members.length} members lose`} the role:{' '}
                                <span className="ph-no-capture">{roleMemberNames(members)}</span>.
                            </AlertDialogDescription>
                        )}
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                        <Button variant="outline" onClick={() => setConfirmOpen(false)}>
                            Cancel
                        </Button>
                        <Button
                            variant="destructive-outline"
                            onClick={() => {
                                setConfirmOpen(false)
                                deleteRole(role.role_id)
                                // The role this dialog shows is gone, so don't stay open on "Role not found"
                                closeAccessDetailDialog()
                            }}
                        >
                            Delete role
                        </Button>
                    </AlertDialogFooter>
                </AlertDialogContent>
            </AlertDialog>
        </div>
    )
}
