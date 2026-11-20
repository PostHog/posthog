import { useId } from 'react'

import {
    Badge,
    Button,
    Dialog,
    DialogBody,
    DialogContent,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Field,
    FieldLabel,
    Input,
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
    Text,
} from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'
import { OrganizationMembershipLevel } from 'lib/constants'

import type { OrganizationBasicType, PersonalAPIKeyType } from '~/types'

import { QuillTagList } from './QuillTagList'
import { ScopeGroupSummary } from './scopes/ScopeGroupSummary'

export interface QuillDeleteUserDialogProps {
    isOpen: boolean
    userLoading: boolean
    organizations: OrganizationBasicType[]
    keys: PersonalAPIKeyType[]
    confirmationText: string
    isUserDeletionConfirmed: boolean
    onClose: () => void
    onDelete: () => void
    onTransferOwnership: (organization: OrganizationBasicType) => void
    onLeaveOrganization: (organization: OrganizationBasicType) => void
    onDeleteOrganization: (organization: OrganizationBasicType) => void
    onConfirmationChange: (value: string) => void
}

export function QuillDeleteUserDialog({
    isOpen,
    userLoading,
    organizations,
    keys,
    confirmationText,
    isUserDeletionConfirmed,
    onClose,
    onDelete,
    onTransferOwnership,
    onLeaveOrganization,
    onDeleteOrganization,
    onConfirmationChange,
}: QuillDeleteUserDialogProps): JSX.Element {
    const inputId = useId()

    const deleteDisabledReason =
        organizations.length > 0
            ? 'Leave or delete your organizations first'
            : !isUserDeletionConfirmed
              ? `Type "${confirmationText}" to confirm`
              : undefined

    return (
        <Dialog
            open={isOpen}
            onOpenChange={(open: boolean) => {
                if (!open && !userLoading) {
                    onClose()
                }
            }}
        >
            <DialogContent showCloseButton={!userLoading}>
                <DialogHeader>
                    <DialogTitle>Delete your account</DialogTitle>
                </DialogHeader>
                <DialogBody>
                    {organizations.length > 0 ? (
                        <div className="flex flex-col gap-2">
                            <Text size="xs" variant="destructive" weight="semibold" render={<p className="m-0" />}>
                                You must leave or delete all organizations before deleting your account.
                            </Text>
                            <Table>
                                <TableHeader>
                                    <TableRow>
                                        <TableHead>Organization</TableHead>
                                        <TableHead />
                                    </TableRow>
                                </TableHeader>
                                <TableBody>
                                    {organizations.map((organization) => {
                                        const isOwner =
                                            organization.membership_level === OrganizationMembershipLevel.Owner

                                        return (
                                            <TableRow key={organization.id}>
                                                <TableCell className="font-semibold">{organization.name}</TableCell>
                                                <TableCell>
                                                    <div className="flex flex-wrap justify-end gap-2">
                                                        {isOwner ? (
                                                            <>
                                                                <Button
                                                                    variant="outline"
                                                                    onClick={() => onTransferOwnership(organization)}
                                                                >
                                                                    Transfer ownership
                                                                </Button>
                                                                <Button
                                                                    variant="destructive-outline"
                                                                    onClick={() => onDeleteOrganization(organization)}
                                                                >
                                                                    Delete organization
                                                                </Button>
                                                            </>
                                                        ) : (
                                                            <Button
                                                                variant="outline"
                                                                onClick={() => onLeaveOrganization(organization)}
                                                            >
                                                                Leave organization
                                                            </Button>
                                                        )}
                                                    </div>
                                                </TableCell>
                                            </TableRow>
                                        )
                                    })}
                                </TableBody>
                            </Table>
                        </div>
                    ) : (
                        <div className="flex flex-col gap-4">
                            <Text size="xs" render={<p className="m-0" />}>
                                Account deletion <b>cannot be undone</b>. You will lose all your data permanently.
                            </Text>

                            {keys.length > 0 && (
                                <div className="flex flex-col gap-2">
                                    <Text
                                        size="xs"
                                        variant="destructive"
                                        weight="semibold"
                                        render={<p className="m-0" />}
                                    >
                                        The following personal API keys will be deleted
                                    </Text>
                                    <Table>
                                        <TableHeader>
                                            <TableRow>
                                                <TableHead>Label</TableHead>
                                                <TableHead>Last Used</TableHead>
                                                <TableHead>Scopes</TableHead>
                                            </TableRow>
                                        </TableHeader>
                                        <TableBody>
                                            {keys.map((key) => (
                                                <TableRow key={key.id}>
                                                    <TableCell className="font-semibold">{key.label}</TableCell>
                                                    <TableCell>
                                                        {key.last_used_at ? (
                                                            <TZLabel time={key.last_used_at} />
                                                        ) : (
                                                            <Text size="xs" variant="muted" render={<span />}>
                                                                Never
                                                            </Text>
                                                        )}
                                                    </TableCell>
                                                    <TableCell>
                                                        {key.scopes[0] === '*' ? (
                                                            <Badge variant="warning">All access</Badge>
                                                        ) : (
                                                            <QuillTagList
                                                                tags={key.scopes}
                                                                tooltip={<ScopeGroupSummary scopes={key.scopes} />}
                                                            />
                                                        )}
                                                    </TableCell>
                                                </TableRow>
                                            ))}
                                        </TableBody>
                                    </Table>
                                </div>
                            )}

                            <Field>
                                <FieldLabel htmlFor={inputId}>
                                    <span>
                                        Please type <strong className="select-none">{confirmationText}</strong> to
                                        confirm account deletion.
                                    </span>
                                </FieldLabel>
                                <Input
                                    id={inputId}
                                    type="text"
                                    onChange={(event) => onConfirmationChange(event.target.value)}
                                />
                            </Field>
                        </div>
                    )}
                </DialogBody>
                <DialogFooter>
                    <Button
                        variant="outline"
                        disabledReason={userLoading ? 'Loading...' : undefined}
                        onClick={onClose}
                        data-attr="delete-user-cancel"
                    >
                        Cancel
                    </Button>
                    <Button
                        variant="destructive-outline"
                        disabledReason={deleteDisabledReason}
                        loading={userLoading}
                        data-attr="delete-user-ok"
                        onClick={onDelete}
                    >
                        Delete account
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
