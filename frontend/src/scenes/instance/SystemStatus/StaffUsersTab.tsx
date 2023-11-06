import { Divider, Modal } from 'antd'
import { useActions, useValues } from 'kea'
import { IconDelete } from 'lib/lemon-ui/icons'
import { LemonTableColumns, LemonTable } from 'lib/lemon-ui/LemonTable'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { UserType } from '~/types'
import { staffUsersLogic } from './staffUsersLogic'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { userLogic } from 'scenes/userLogic'
import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'
import { LemonSelectMultiple } from 'lib/lemon-ui/LemonSelectMultiple/LemonSelectMultiple'
import { usersLemonSelectOptions } from 'lib/components/UserSelectItem'
import { Link } from '@posthog/lemon-ui'

export function StaffUsersTab(): JSX.Element {
    const { user: myself } = useValues(userLogic)
    const { staffUsers, allUsersLoading, nonStaffUsers, staffUsersToBeAdded } = useValues(staffUsersLogic)
    const { setStaffUsersToBeAdded, addStaffUsers, deleteStaffUser } = useActions(staffUsersLogic)

    const columns: LemonTableColumns<UserType> = [
        {
            key: 'profile_picture',
            render: function ProfilePictureRender(_, user) {
                return <ProfilePicture name={user.first_name} email={user.email} />
            },
            width: 32,
        },
        {
            key: 'name',
            title: 'Name',
            dataIndex: 'first_name',
            render: function ProfilePictureRender(_, user) {
                return (
                    <>
                        {user.first_name}
                        {user.uuid === myself?.uuid && <LemonTag className="uppercase ml-1">Me</LemonTag>}
                    </>
                )
            },
        },
        {
            key: 'email',
            title: 'Email',
            dataIndex: 'email',
        },
        {
            key: 'actions',
            width: 32,
            render: function RenderActions(_, user) {
                return (
                    <LemonButton
                        data-attr="invite-delete"
                        icon={<IconDelete />}
                        status="danger"
                        disabled={staffUsers.length < 2}
                        title={
                            staffUsers.length < 2
                                ? 'You should always have at least one staff user.'
                                : 'Cancel the invite'
                        }
                        onClick={() => {
                            Modal.confirm({
                                title: `Remove ${
                                    myself?.uuid === user.uuid ? 'yourself' : user.first_name
                                } as a Staff User?`,
                                icon: null,
                                okText: 'Remove user',
                                okType: 'primary',
                                okButtonProps: { className: 'btn-danger' },
                                content: (
                                    <div style={{ border: '' }}>
                                        {myself?.uuid === user.uuid ? (
                                            <>
                                                Please confirm you want to <b>remove yourself</b> as a staff user.
                                                <div
                                                    style={{
                                                        fontWeight: 'normal',
                                                        color: 'var(--muted-alt)',
                                                    }}
                                                >
                                                    Only another staff user will be able to add you again.
                                                </div>
                                            </>
                                        ) : (
                                            `Are you sure you want to remove ${user.first_name} as a Staff User?`
                                        )}
                                    </div>
                                ),
                                onOk() {
                                    deleteStaffUser(user.uuid)
                                },
                                cancelText: 'Cancel',
                            })
                        }}
                    />
                )
            },
        },
    ]

    return (
        <div>
            <h3 className="l3" style={{ marginTop: 16 }}>
                Staff Users
            </h3>
            <div className="mb-4">
                Users who have permissions to manage instance-wide settings. Staff user permissions are set at the{' '}
                <b>instance-level and are independent of any organization or project permissions.</b>{' '}
                <Link
                    to="https://posthog.com/docs/self-host/configure/instance-settings#staff-users"
                    target="_blank"
                    targetBlankIcon
                >
                    Learn more
                </Link>
                .
            </div>
            <Divider style={{ margin: 0, marginBottom: 16 }} />
            <section>
                <div className="flex gap-2 mb-4">
                    <div className="flex flex-1">
                        <LemonSelectMultiple
                            placeholder="Add staff users here…"
                            loading={allUsersLoading}
                            value={staffUsersToBeAdded}
                            onChange={(newValues: string[]) => setStaffUsersToBeAdded(newValues)}
                            filterOption={true}
                            mode="multiple"
                            data-attr="subscribed-emails"
                            options={usersLemonSelectOptions(nonStaffUsers, 'uuid')}
                        />
                    </div>
                    <LemonButton
                        type="primary"
                        loading={allUsersLoading}
                        disabled={staffUsersToBeAdded.length === 0}
                        onClick={addStaffUsers}
                    >
                        Add
                    </LemonButton>
                </div>
            </section>
            <LemonTable dataSource={staffUsers} columns={columns} loading={allUsersLoading} rowKey="uuid" />
        </div>
    )
}
