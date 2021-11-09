import React, { useState } from 'react'
import { useActions, useValues } from 'kea'
import { Button, Form, Select } from 'antd'
import Modal from 'antd/lib/modal/Modal'
import { UserAddOutlined } from '@ant-design/icons'
import { teamMembersLogic } from './teamMembersLogic'
import { teamLogic } from 'scenes/teamLogic'
import { ProfilePicture } from '../../../lib/components/ProfilePicture'
import { membershipLevelToName, teamMembershipLevelIntegers } from '../../../lib/utils/permissioning'
import { TeamMembershipLevel } from '../../../lib/constants'
import { useForm } from 'antd/lib/form/Form'
import { RestrictedComponentProps } from '../../../lib/components/RestrictedArea'

export function AddMembersModalWithButton({ isRestricted }: RestrictedComponentProps): JSX.Element {
    const { addMembers } = useActions(teamMembersLogic)
    const { addableMembers, allMembersLoading } = useValues(teamMembersLogic)
    const { currentTeam } = useValues(teamLogic)

    const [form] = useForm()
    const [isVisible, setIsVisible] = useState(false)

    function closeModal(): void {
        form.resetFields()
        setIsVisible(false)
    }

    async function handleOnFinish(): Promise<void> {
        await form.validateFields()
        const { userUuids, level } = form.getFieldsValue()
        addMembers({ userUuids, level })
        closeModal()
    }

    return (
        <>
            <Button
                type="primary"
                data-attr="add-project-members-button"
                onClick={() => {
                    setIsVisible(true)
                }}
                icon={<UserAddOutlined />}
                disabled={isRestricted}
            >
                Add members to project
            </Button>
            <Modal
                title={`Adding members${currentTeam?.name ? ` to project ${currentTeam.name}` : ''}`}
                okText="Add members to project"
                onOk={handleOnFinish}
                okButtonProps={{
                    // @ts-expect-error - data-attr works just fine despite not being in ButtonProps
                    'data-attr': 'add-project-members-submit',
                }}
                onCancel={closeModal}
                visible={isVisible}
            >
                <Form form={form} onFinish={handleOnFinish}>
                    <Form.Item
                        rules={[
                            {
                                required: true,
                                message: 'Select at least one member to add.',
                                type: 'array',
                            },
                        ]}
                        style={{ marginBottom: 8 }}
                        name="userUuids"
                    >
                        <Select
                            mode="multiple"
                            placeholder="Organization members"
                            optionFilterProp="title"
                            loading={allMembersLoading}
                            showArrow
                            showSearch
                            autoFocus
                        >
                            {addableMembers.map((member) => (
                                <Select.Option
                                    key={member.id}
                                    value={member.user.uuid}
                                    title={`${member.user.first_name} (${member.user.email})`}
                                    disabled={!!member.level}
                                >
                                    <ProfilePicture
                                        name={member.user.first_name}
                                        email={member.user.email}
                                        size="sm"
                                        style={{ display: 'inline-flex', marginRight: 8 }}
                                    />
                                    {member.user.first_name} ({member.user.email})
                                    {!!member.level && <i> – already has project access</i>}
                                </Select.Option>
                            ))}
                        </Select>
                    </Form.Item>
                    <Form.Item
                        label="With project-specific access level"
                        style={{ marginBottom: 0 }}
                        name="level"
                        initialValue={TeamMembershipLevel.Member}
                    >
                        <Select
                            options={teamMembershipLevelIntegers.map((teamMembershipLevel) => ({
                                value: teamMembershipLevel,
                                label: membershipLevelToName.get(teamMembershipLevel),
                            }))}
                            showArrow
                        />
                    </Form.Item>
                </Form>
            </Modal>
        </>
    )
}
