import { LemonButton, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { RestrictedComponentProps } from 'lib/components/RestrictedArea'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { useState } from 'react'
import { urls } from 'scenes/urls'

import { AccessLevel, RoleType } from '~/types'

import { CreateRoleModal } from './CreateRoleModal'
import { rolesLogic } from './rolesLogic'

export function Roles({ isRestricted }: RestrictedComponentProps): JSX.Element {
    const { roles, rolesLoading } = useValues(rolesLogic)
    const { setRoleInFocus, openCreateRoleModal, deleteRole } = useActions(rolesLogic)
    const [activeKey, setActiveKey] = useState('members')

    const columns: LemonTableColumns<RoleType> = [
        {
            key: 'name',
            title: 'Role',
            dataIndex: 'name',
            render: function RoleNameRender(_, role) {
                return (
                    <div
                        className="row-name text-link cursor-pointer"
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
                            isRestricted ? (
                                "You don't have permission to delete roles"
                            ) : (
                                <LemonButton onClick={() => deleteRole(role)} status="danger">
                                    Delete
                                </LemonButton>
                            )
                        }
                    />
                )
            },
        },
    ]

    return (
        <>
            <div className="flex items-center">
                <div className="grow">
                    <h2 id="roles" className="subtitle">
                        Roles
                    </h2>
                    <p className="text-muted-alt">
                        Create roles to provide fine-grained permissions to users across posthog resources. Admins+ will
                        always have full edit access regardless of default or role.
                    </p>
                </div>

                {!isRestricted && (
                    <LemonButton type="primary" onClick={openCreateRoleModal} data-attr="create-role-button">
                        Create role
                    </LemonButton>
                )}
            </div>
            <LemonTable
                dataSource={roles}
                columns={columns}
                rowKey={() => 'id'}
                expandable={{
                    expandedRowRender: function RenderRolesTable(role) {
                        return (
                            <LemonTabs
                                activeKey={activeKey}
                                onChange={setActiveKey}
                                tabs={[
                                    {
                                        key: 'members',
                                        label: 'Members',
                                        content: (
                                            <div className="flex flex-col my-4">
                                                {role.members.map((member) => (
                                                    <div key={member.id}>{member.user.first_name}</div>
                                                ))}
                                            </div>
                                        ),
                                    },
                                    {
                                        key: 'feature-flags',
                                        label: 'Feature flags',
                                        content: (
                                            <div className="mb-4">
                                                {role.feature_flags_access_level === AccessLevel.WRITE ? (
                                                    'All'
                                                ) : (
                                                    <div className="flex flex-col">
                                                        {role.associated_flags.map((flag) => (
                                                            <Link key={flag.id} to={urls.featureFlag(flag.id)}>
                                                                {flag.key}
                                                            </Link>
                                                        ))}
                                                    </div>
                                                )}
                                            </div>
                                        ),
                                    },
                                ]}
                            />
                        )
                    },
                }}
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
