import { Button, Col, Input, Row } from 'antd'
import Modal from 'antd/lib/modal/Modal'
import { useActions, useValues } from 'kea'
import React from 'react'
import { userLogic } from 'scenes/userLogic'
import { PlusOutlined } from '@ant-design/icons'
import './BulkInviteModal.scss'
import { capitalizeFirstLetter, isEmail } from 'lib/utils'
import { bulkInviteLogic } from './bulkInviteLogic'

const PLACEHOLDER_NAMES = ['jane', 'john']

function InviteRow({ index }: { index: number }): JSX.Element {
    const name = PLACEHOLDER_NAMES[index % 2]
    const { invites } = useValues(bulkInviteLogic)
    const { updateInviteAtIndex } = useActions(bulkInviteLogic)

    return (
        <Row gutter={16} className="invite-row">
            <Col xs={12}>
                <Input
                    placeholder={`${name}@posthog.com`}
                    type="email"
                    className={`error-on-blur${!invites[index].isValid ? ' errored' : ''}`}
                    onChange={(e) => {
                        const { value } = e.target
                        let isValid = true
                        if (value && !isEmail(value)) {
                            isValid = false
                        }
                        updateInviteAtIndex({ email: e.target.value, isValid }, index)
                    }}
                    value={invites[index].email}
                />
            </Col>
            <Col xs={12}>
                <Input
                    placeholder={capitalizeFirstLetter(name)}
                    onBlur={(e) => {
                        updateInviteAtIndex({ first_name: e.target.value }, index)
                    }}
                />
            </Col>
        </Row>
    )
}

export function BulkInviteModal({ visible, onClose }: { visible: boolean; onClose: () => void }): JSX.Element {
    const { user } = useValues(userLogic)
    const { invites, canSubmit } = useValues(bulkInviteLogic)
    const { addMoreInvites, resetInvites } = useActions(bulkInviteLogic)

    return (
        <>
            <Modal
                title={`Invite your team members${user?.organization ? ' to ' + user?.organization?.name : ''}`}
                visible={visible}
                onCancel={() => {
                    resetInvites()
                    onClose()
                }}
                okText="Invite team members"
                destroyOnClose
                okButtonProps={{ disabled: !canSubmit }}
            >
                <div className="bulk-invite-modal">
                    <div>
                        Invite as many team members as you want. <b>Names are optional</b>, but it will speed up the
                        process for your teammates.
                    </div>
                    <Row gutter={16} className="mt">
                        <Col xs={12}>
                            <b>Email (required)</b>
                        </Col>
                        <Col xs={12}>
                            <b>First Name</b>
                        </Col>
                    </Row>

                    {invites.map((_, index) => (
                        <InviteRow index={index} key={index.toString()} />
                    ))}

                    <div className="mt">
                        <Button block className="btn-add" onClick={addMoreInvites}>
                            <PlusOutlined /> Add more team members
                        </Button>
                    </div>
                </div>
            </Modal>
        </>
    )
}
