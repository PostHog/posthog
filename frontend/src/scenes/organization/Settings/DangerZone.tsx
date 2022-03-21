import { useActions, useValues } from 'kea'
import { DeleteOutlined } from '@ant-design/icons'
import { Button, Input, Modal } from 'antd'
import { organizationLogic } from 'scenes/organizationLogic'
import Paragraph from 'antd/lib/typography/Paragraph'
import { RestrictedComponentProps } from '../../../lib/components/RestrictedArea'
import React, { Dispatch, SetStateAction, useState } from 'react'

export function DeleteOrganizationModal({
    isVisible,
    setIsVisible,
}: {
    isVisible: boolean
    setIsVisible: Dispatch<SetStateAction<boolean>>
}): JSX.Element {
    const { currentOrganization, organizationBeingDeleted } = useValues(organizationLogic)
    const { deleteOrganization } = useActions(organizationLogic)

    const [isDeletionConfirmed, setIsDeletionConfirmed] = useState(false)
    const isDeletionInProgress = !!currentOrganization && organizationBeingDeleted?.id === currentOrganization.id

    return (
        <Modal
            title="Delete the entire organization?"
            okText={`Delete ${currentOrganization ? currentOrganization.name : 'the current organization'}`}
            onOk={currentOrganization ? () => deleteOrganization(currentOrganization) : undefined}
            okType="primary"
            okButtonProps={{
                // @ts-expect-error - data-attr works just fine despite not being in ButtonProps
                'data-attr': 'delete-organization-ok',
                loading: isDeletionInProgress,
                disabled: !isDeletionConfirmed,
                className: 'btn-danger',
            }}
            onCancel={() => setIsVisible(false)}
            cancelButtonProps={{
                disabled: isDeletionInProgress,
            }}
            visible={isVisible}
        >
            <p>
                Organization deletion <b>cannot be undone</b>. You will lose all data, <b>including all events</b>,
                related to all projects within this organization.
            </p>
            <p>
                Please type{' '}
                <strong>{currentOrganization ? currentOrganization.name : "this organization's name"}</strong> to
                confirm.
            </p>
            <Input
                type="text"
                onChange={(e) => {
                    if (currentOrganization) {
                        const { value } = e.target
                        setIsDeletionConfirmed(value.toLowerCase() === currentOrganization.name.toLowerCase())
                    }
                }}
            />
        </Modal>
    )
}

export function DangerZone({ isRestricted }: RestrictedComponentProps): JSX.Element {
    const { currentOrganization } = useValues(organizationLogic)

    const [isModalVisible, setIsModalVisible] = useState(false)

    return (
        <>
            <div style={{ color: 'var(--danger)' }}>
                <h2 style={{ color: 'var(--danger)' }} className="subtitle">
                    Danger Zone
                </h2>
                <div className="mt">
                    {!isRestricted && (
                        <Paragraph type="danger">
                            This is <b>irreversible</b>. Please be certain.
                        </Paragraph>
                    )}
                    <Button
                        type="primary"
                        onClick={() => setIsModalVisible(true)}
                        className="mr-05 btn-danger"
                        data-attr="delete-project-button"
                        icon={<DeleteOutlined />}
                        disabled={isRestricted}
                    >
                        Delete {currentOrganization?.name || 'the current organization'}
                    </Button>
                </div>
            </div>
            <DeleteOrganizationModal isVisible={isModalVisible} setIsVisible={setIsModalVisible} />
        </>
    )
}
