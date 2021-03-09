import React from 'react'
import { useActions, useValues } from 'kea'
import { ExclamationCircleOutlined, DeleteOutlined } from '@ant-design/icons'
import { red } from '@ant-design/colors'
import { Button } from 'antd'
import confirm from 'antd/lib/modal/confirm'
import { organizationLogic } from 'scenes/organizationLogic'
import Paragraph from 'antd/lib/typography/Paragraph'
import { RestrictedComponentProps } from '../../../lib/components/RestrictedArea'

export function DangerZone({ isRestricted }: RestrictedComponentProps): JSX.Element {
    const { currentOrganization } = useValues(organizationLogic)
    const { deleteCurrentOrganization } = useActions(organizationLogic)

    function confirmDeleteProject(): void {
        confirm({
            title: 'Delete the entire organization?',
            content: (
                <>
                    Organization deletion <b>cannot be undone</b>. You will lose all data, <b>including all events</b>,
                    related to all projects within this organization.
                </>
            ),
            icon: <ExclamationCircleOutlined color={red.primary} />,
            okText: currentOrganization ? `Delete ${currentOrganization.name}` : <i>Loading current organization…</i>,
            okType: 'danger',
            okButtonProps: {
                // @ts-expect-error - data-attr works just fine despite not being in ButtonProps
                'data-attr': 'delete-organization-ok',
            },
            cancelText: 'Cancel',
            onOk: deleteCurrentOrganization,
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
                    Delete {currentOrganization?.name || 'the current organization'}
                </Button>
            </div>
        </div>
    )
}
