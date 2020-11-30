import React from 'react'
import { useActions, useValues } from 'kea'
import { ExclamationCircleOutlined, LockOutlined } from '@ant-design/icons'
import { red } from '@ant-design/colors'
import { Button } from 'antd'
import { teamLogic } from 'scenes/teamLogic'
import confirm from 'antd/lib/modal/confirm'
import { organizationLogic } from 'scenes/organizationLogic'
import { OrganizationMembershipLevel } from 'lib/constants'

export function DangerZone(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const { deleteCurrentTeam } = useActions(teamLogic)

    function confirmDeleteProject(): void {
        confirm({
            title: currentTeam ? `Delete project ${currentTeam.name}?` : <i>Loading current project…</i>,
            content: 'Project deletion cannot be undone. You will lose all data within your project.',
            icon: <ExclamationCircleOutlined color={red.primary} />,
            okText: currentTeam ? `Delete ${currentTeam.name}` : <i>Loading current project…</i>,
            okType: 'danger',
            okButtonProps: {
                'data-attr': 'delete-project-ok',
            },
            cancelText: 'Cancel',
            onOk() {
                deleteCurrentTeam()
                location.reload()
            },
        })
    }

    let accessRestrictionReason: string | null = null
    if ((currentOrganization?.membership_level ?? -1) < OrganizationMembershipLevel.Admin) {
        accessRestrictionReason = 'This section is restricted to administrators.'
    }

    return accessRestrictionReason ? (
        <div className="access-restricted">
            <LockOutlined className="text-warning" />
            {accessRestrictionReason}
        </div>
    ) : (
        <div className="mt">
            <Button
                type="primary"
                danger
                onClick={confirmDeleteProject}
                className="mr-05"
                data-attr="delete-project-button"
            >
                Delete Project
            </Button>
            This will <b>permanently delete</b> your project and data associated to it. Please be certain.
        </div>
    )
}
