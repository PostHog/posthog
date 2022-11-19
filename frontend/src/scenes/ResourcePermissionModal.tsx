import { LemonButton, LemonModal } from '@posthog/lemon-ui'
import { IconDelete } from 'lib/components/icons'
import {
    LemonSelectMultiple,
    LemonSelectMultipleOptionItem,
} from 'lib/components/LemonSelectMultiple/LemonSelectMultiple'
import { RoleType } from '~/types'

interface ResourcePermissionModalProps {
    title: string
    visible: boolean
    onClose: () => void
    addableRoles: RoleType[]
    addableRolesLoading: boolean
    onChange: (newValue: string[]) => void
    rolesToAdd: string[]
    onAdd: () => void
    roles: RoleType[]
    deleteAssociatedRole: (id: RoleType['id']) => void
}

export function roleLemonSelectOptions(roles: RoleType[]): LemonSelectMultipleOptionItem[] {
    return roles.map((role) => ({
        key: role.id,
        label: `${role.name}`,
        labelComponent: (
            <span>
                <b>{`${role.name}`}</b>
            </span>
        ),
    }))
}

export function ResourcePermissionModal({
    title,
    visible,
    onClose,
    rolesToAdd,
    addableRoles,
    onChange,
    addableRolesLoading,
    onAdd,
    roles,
    deleteAssociatedRole,
}: ResourcePermissionModalProps): JSX.Element {
    return (
        <LemonModal title={title} isOpen={visible} onClose={onClose}>
            <div className="flex gap-2">
                <div className="flex-1">
                    <LemonSelectMultiple
                        placeholder="Search for roles to add…"
                        loading={addableRolesLoading}
                        onChange={onChange}
                        value={rolesToAdd}
                        filterOption={true}
                        mode="multiple"
                        data-attr="resource-permissioning-select"
                        options={roleLemonSelectOptions(addableRoles)}
                    />
                </div>
                <LemonButton type="primary" loading={false} disabled={rolesToAdd.length === 0} onClick={onAdd}>
                    Add
                </LemonButton>
            </div>
            <h5 className="mt-4">Roles</h5>
            {roles.length > 0 ? (
                <div
                    className="mt-2 pb-2 rounded overflow-y-auto"
                    style={{
                        maxHeight: 300,
                    }}
                >
                    {roles.map((role) => {
                        return (
                            <RoleRow key={role.id} role={role} deleteRole={(roleId) => deleteAssociatedRole(roleId)} />
                        )
                    })}
                </div>
            ) : (
                <div className="text-muted mb-2">No members added yet</div>
            )}
        </LemonModal>
    )
}

function RoleRow({ role, deleteRole }: { role: RoleType; deleteRole?: (roleId: RoleType['id']) => void }): JSX.Element {
    return (
        <div className="flex items-center justify-between mt-2 h-8">
            <b>{role.name}</b>
            {deleteRole && (
                <LemonButton
                    icon={<IconDelete />}
                    onClick={() => deleteRole(role.id)}
                    tooltip={'Remove role from permission'}
                    status="primary-alt"
                    type="tertiary"
                    size="small"
                />
            )}
        </div>
    )
}
