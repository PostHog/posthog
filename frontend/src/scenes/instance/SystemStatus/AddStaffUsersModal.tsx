import { Button, Select } from 'antd'
import { useActions, useValues } from 'kea'
import { LemonModal } from 'lib/components/LemonModal/LemonModal'
import { ProfilePicture } from 'lib/components/ProfilePicture'
import React, { useEffect } from 'react'
import { staffUsersLogic } from './staffUsersLogic'

export function AddStaffUsersModal(): JSX.Element {
    const onCancel = (): void => {}
    const { nonStaffUsers, nonStaffUsersLoading, staffUsersToBeAdded } = useValues(staffUsersLogic)
    const { loadNonStaffUsers, setStaffUsersToBeAdded } = useActions(staffUsersLogic)

    useEffect(() => loadNonStaffUsers(), [])
    return (
        <LemonModal visible onCancel={onCancel}>
            <section>
                <h5>Add Staff Users</h5>
                <div style={{ display: 'flex', marginBottom: '0.75rem' }}>
                    {/* TOOD: Use Lemon instead of Ant components here */}
                    <Select
                        mode="multiple"
                        placeholder="Search for team members to add…"
                        loading={nonStaffUsersLoading}
                        value={staffUsersToBeAdded}
                        onChange={(newValues) => setStaffUsersToBeAdded(newValues)}
                        showArrow
                        showSearch
                        style={{ flexGrow: 1 }}
                    >
                        {nonStaffUsers.map((user) => (
                            <Select.Option
                                key={user.uuid}
                                value={user.uuid}
                                title={`${user.first_name} (${user.email})`}
                            >
                                <ProfilePicture
                                    name={user.first_name}
                                    email={user.email}
                                    size="sm"
                                    style={{ display: 'inline-flex', marginRight: 8 }}
                                />
                                {user.first_name} ({user.email})
                            </Select.Option>
                        ))}
                    </Select>
                    <Button
                        type="primary"
                        style={{ flexShrink: 0, marginLeft: '0.5rem' }}
                        loading={nonStaffUsersLoading}
                        disabled={staffUsersToBeAdded.length === 0}
                        //onClick={() => addExplicitCollaborators()}
                    >
                        Add
                    </Button>
                </div>
            </section>
        </LemonModal>
    )
}
