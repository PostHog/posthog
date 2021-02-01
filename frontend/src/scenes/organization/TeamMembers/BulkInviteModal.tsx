import { Button, Col, Input, Row } from 'antd'
import Modal from 'antd/lib/modal/Modal'
import { useActions, useValues } from 'kea'
import React from 'react'
import { userLogic } from 'scenes/userLogic'
import { PlusOutlined } from '@ant-design/icons'
import './BulkInviteModal.scss'
import { capitalizeFirstLetter } from 'lib/utils'
import { bulkInviteLogic, InviteType } from './bulkInviteLogic'

const PLACEHOLDER_NAMES = ['jane', 'john']

function InviteRow({ index }: { index: number }): JSX.Element {
    const name = PLACEHOLDER_NAMES[index % 2]
    return (
        <Row gutter={16} className="invite-row">
            <Col xs={12}>
                <Input placeholder={`${name}@posthog.com`} type="email" />
            </Col>
            <Col xs={12}>
                <Input placeholder={capitalizeFirstLetter(name)} />
            </Col>
        </Row>
    )
}

export function BulkInviteModal({ visible, onClose }: { visible: boolean; onClose: () => void }): JSX.Element {
    const { user } = useValues(userLogic)
    const { invites } = useValues(bulkInviteLogic)
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

                    {invites.map((invite: InviteType, index) => (
                        <InviteRow index={index} key={`${invite.email}${index}`} />
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
