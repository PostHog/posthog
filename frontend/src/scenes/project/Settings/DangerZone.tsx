import React from 'react'
import { useActions, useValues } from 'kea'
import { ExclamationCircleOutlined, LockOutlined, DeleteOutlined } from '@ant-design/icons'
import { red } from '@ant-design/colors'
import { Button } from 'antd'
import { teamLogic } from 'scenes/teamLogic'
import confirm from 'antd/lib/modal/confirm'
import { organizationLogic } from 'scenes/organizationLogic'
import { OrganizationMembershipLevel } from 'lib/constants'
import Paragraph from 'antd/lib/typography/Paragraph'

export function DangerZone(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { currentOrganization } = useValues(organizationLogic)
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

    let accessRestrictionReason: string | null = null
    if ((currentOrganization?.membership_level ?? -1) < OrganizationMembershipLevel.Admin) {
        accessRestrictionReason = 'This section is restricted to administrators.'
    }

    return !currentTeam || accessRestrictionReason ? (
        <div className="access-restricted">
            <LockOutlined className="text-warning" />
            {accessRestrictionReason}
        </div>
    ) : (
        <div className="mt">
            <Paragraph type="danger">
                This is <b>irreversible</b>. Please be certain.
            </Paragraph>
            <Button
                type="default"
                danger
                onClick={confirmDeleteProject}
                className="mr-05"
                data-attr="delete-project-button"
                icon={<DeleteOutlined />}
            >
                Delete {currentTeam.name}
            </Button>
        </div>
    )
}
