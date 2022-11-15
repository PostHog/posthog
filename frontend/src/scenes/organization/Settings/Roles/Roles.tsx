import { LemonButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { More } from 'lib/components/LemonButton/More'
import { LemonTable, LemonTableColumns } from 'lib/components/LemonTable'
import { RoleType } from '~/types'
import { CreateRoleModal } from './CreateRoleModal'
import { rolesLogic } from './rolesLogic'

export function Roles(): JSX.Element {
    const { roles, rolesLoading } = useValues(rolesLogic)
    const { setRoleInFocus, openCreateRoleModal, deleteRole } = useActions(rolesLogic)

    const columns: LemonTableColumns<RoleType> = [
        {
            key: 'name',
            title: 'Role',
            dataIndex: 'name',
            render: function RoleNameRender(_, role) {
                return (
                    <div
                        className="row-name text-primary cursor-pointer"
                        onClick={() => {
                            setRoleInFocus(role)
                        }}
                    >
                        {role.name}
                    </div>
                )
            },
        },
        {
            key: 'actions',
            width: 0,
            sticky: true,
            render: function renderActions(_, role) {
                return (
                    <More
                        overlay={
                            <LemonButton onClick={() => deleteRole(role)} status="danger">
                                Delete
                            </LemonButton>
                        }
                    />
                )
            },
        },
    ]

    return (
        <>
            <h2 id="roles" className="subtitle" style={{ justifyContent: 'space-between' }}>
                Roles
                <LemonButton type="primary" onClick={openCreateRoleModal} data-attr="create-role-button">
                    Create Role
                </LemonButton>
            </h2>
            <LemonTable
                dataSource={roles}
                columns={columns}
                rowKey={() => 'id'}
                style={{ marginTop: '1rem' }}
                loading={rolesLoading}
                data-attr="org-roles-table"
                defaultSorting={{ columnKey: 'level', order: -1 }}
                pagination={{ pageSize: 50 }}
            />
            <CreateRoleModal />
        </>
    )
}
