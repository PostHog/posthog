import { LemonButton, LemonModal } from '@posthog/lemon-ui'
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
                <LemonButton type="primary" loading={false} disabled={rolesToAdd.length === 0} onClick={() => {}}>
                    Add
                </LemonButton>
            </div>
        </LemonModal>
    )
}
