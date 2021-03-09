import React from 'react'
import { useActions, useValues } from 'kea'
import { ExclamationCircleOutlined, DeleteOutlined } from '@ant-design/icons'
import { red } from '@ant-design/colors'
import { Button } from 'antd'
import { teamLogic } from 'scenes/teamLogic'
import confirm from 'antd/lib/modal/confirm'
import Paragraph from 'antd/lib/typography/Paragraph'
import { RestrictedComponentProps } from '../../../lib/components/RestrictedArea'

export function DangerZone({ isRestricted }: RestrictedComponentProps): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { deleteCurrentTeam } = useActions(teamLogic)

    function confirmDeleteProject(): void {
        confirm({
            title: 'Delete the entire project?',
            content: (
                <>
                    Project deletion <b>cannot be undone</b>. You will lose all data, <b>including events</b>, related
                    to the project.
                </>
            ),
            icon: <ExclamationCircleOutlined color={red.primary} />,
            okText: currentTeam ? `Delete ${currentTeam.name}` : <i>Loading current project…</i>,
            okType: 'danger',
            okButtonProps: {
                // @ts-expect-error - data-attr works just fine despite not being in ButtonProps
                'data-attr': 'delete-project-ok',
            },
            cancelText: 'Cancel',
            onOk: deleteCurrentTeam,
        })
    }
    return (
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
                    type="default"
                    danger
                    onClick={confirmDeleteProject}
                    className="mr-05"
                    data-attr="delete-project-button"
                    icon={<DeleteOutlined />}
                    disabled={isRestricted}
                >
                    Delete {currentTeam?.name || 'the current project'}
                </Button>
            </div>
        </div>
    )
}
