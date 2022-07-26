import React, { Dispatch, SetStateAction, useState } from 'react'
import { useActions, useValues } from 'kea'
import { DeleteOutlined } from '@ant-design/icons'
import { Button, Input, Modal } from 'antd'
import { teamLogic } from 'scenes/teamLogic'
import Paragraph from 'antd/lib/typography/Paragraph'
import { RestrictedComponentProps } from '../../../lib/components/RestrictedArea'

export function DeleteProjectModal({
    isVisible,
    setIsVisible,
}: {
    isVisible: boolean
    setIsVisible: Dispatch<SetStateAction<boolean>>
}): JSX.Element {
    const { currentTeam, teamBeingDeleted } = useValues(teamLogic)
    const { deleteTeam } = useActions(teamLogic)

    const [isDeletionConfirmed, setIsDeletionConfirmed] = useState(false)
    const isDeletionInProgress = !!currentTeam && teamBeingDeleted?.id === currentTeam.id

    return (
        <Modal
            title="Delete the project and its data?"
            okText={`Delete ${currentTeam ? currentTeam.name : 'the current project'}`}
            okType="danger"
            onOk={currentTeam ? () => deleteTeam(currentTeam) : undefined}
            okButtonProps={{
                // @ts-expect-error - data-attr works just fine despite not being in ButtonProps
                'data-attr': 'delete-project-ok',
                loading: isDeletionInProgress,
                disabled: !isDeletionConfirmed,
            }}
            onCancel={() => setIsVisible(false)}
            cancelButtonProps={{
                disabled: isDeletionInProgress,
            }}
            visible={isVisible}
        >
            <p>
                Project deletion <b>cannot be undone</b>. You will lose all data, <b>including events</b>, related to
                the project.
            </p>
            <p>
                Please type <strong>{currentTeam ? currentTeam.name : "this project's name"}</strong> to confirm.
            </p>
            <Input
                type="text"
                onChange={(e) => {
                    if (currentTeam) {
                        const { value } = e.target
                        setIsDeletionConfirmed(value.toLowerCase() === currentTeam.name.toLowerCase())
                    }
                }}
            />
        </Modal>
    )
}

export function DangerZone({ isRestricted }: RestrictedComponentProps): JSX.Element {
    const { currentTeam } = useValues(teamLogic)

    const [isModalVisible, setIsModalVisible] = useState(false)

    return (
        <>
            <div style={{ color: 'var(--danger)' }}>
                <h2 style={{ color: 'var(--danger)' }} className="subtitle">
                    Danger Zone
                </h2>
                <div className="mt-4">
                    {!isRestricted && (
                        <Paragraph type="danger">
                            This is <b>irreversible</b>. Please be certain.
                        </Paragraph>
                    )}
                    <Button
                        type="default"
                        danger
                        onClick={() => setIsModalVisible(true)}
                        className="mr-2"
                        data-attr="delete-project-button"
                        icon={<DeleteOutlined />}
                        disabled={isRestricted}
                    >
                        Delete {currentTeam?.name || 'the current project'}
                    </Button>
                </div>
            </div>
            <DeleteProjectModal isVisible={isModalVisible} setIsVisible={setIsModalVisible} />
        </>
    )
}
