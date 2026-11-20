import { useActions, useValues } from 'kea'
import { Form, Field as KeaField } from 'kea-forms'

import {
    Button,
    Dialog,
    DialogBody,
    DialogContent,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Field,
    FieldError,
    FieldLabel,
    Input,
} from '@posthog/quill'

import { organizationLogic } from 'scenes/organizationLogic'

import { roleAccessControlLogic } from '../roleAccessControlLogic'
import { confirmDeleteRole } from '../roleActions'

export function QuillRoleDialog(): JSX.Element {
    const { editingRoleId, isEditingRoleSubmitting } = useValues(roleAccessControlLogic)
    const { setEditingRoleId, deleteRole } = useActions(roleAccessControlLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const isEditing = editingRoleId !== 'new'

    const isDefaultRole = currentOrganization?.default_role_id === editingRoleId

    return (
        <Dialog
            open={!!editingRoleId}
            onOpenChange={(open: boolean) => {
                if (!open) {
                    setEditingRoleId(null)
                }
            }}
        >
            <DialogContent>
                <Form logic={roleAccessControlLogic} formKey="editingRole" enableFormOnSubmit>
                    <DialogHeader>
                        <DialogTitle>{!isEditing ? 'Create' : 'Edit'}</DialogTitle>
                    </DialogHeader>
                    <DialogBody>
                        <KeaField name="name" noStyle>
                            {({ id, value, onChange, error }) => (
                                <Field data-invalid={error ? true : undefined}>
                                    <FieldLabel htmlFor={id}>Role name</FieldLabel>
                                    <Input
                                        id={id}
                                        value={value ?? ''}
                                        onChange={(event) => onChange(event.target.value)}
                                        placeholder="Please enter a name..."
                                        autoFocus
                                    />
                                    {error && <FieldError>{error}</FieldError>}
                                </Field>
                            )}
                        </KeaField>
                    </DialogBody>
                    <DialogFooter>
                        {isEditing && (
                            <Button
                                variant="destructive-outline"
                                className="sm:mr-auto"
                                onClick={() =>
                                    confirmDeleteRole(isDefaultRole, () => deleteRole(editingRoleId as string))
                                }
                            >
                                Delete
                            </Button>
                        )}
                        <Button variant="outline" onClick={() => setEditingRoleId(null)}>
                            Cancel
                        </Button>
                        <Button variant="primary" type="submit" loading={isEditingRoleSubmitting}>
                            {!isEditing ? 'Create' : 'Save'}
                        </Button>
                    </DialogFooter>
                </Form>
            </DialogContent>
        </Dialog>
    )
}
