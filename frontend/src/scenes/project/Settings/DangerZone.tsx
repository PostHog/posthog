import React from 'react'
import { useActions, useValues } from 'kea'
import { ExclamationCircleOutlined } from '@ant-design/icons'
import { red } from '@ant-design/colors'
import { Button, Tooltip } from 'antd'
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
            cancelText: 'Cancel',
            onOk() {
                deleteCurrentTeam()
                location.reload()
            },
        })
    }

    let accessRestrictionReason: string | null = null
    if ((currentOrganization?.membership_level ?? -1) < OrganizationMembershipLevel.Admin)
        accessRestrictionReason = 'This section is restricted to users at or above administrator level.'

    const Content = (
        <Button type="primary" danger onClick={confirmDeleteProject}>
            Delete Project
        </Button>
    )

    return accessRestrictionReason ? (
        <Tooltip title={accessRestrictionReason}>
            <div className="overlay__parent overlay--danger">
                {Content}
                <div className="overlay__child" />
            </div>
        </Tooltip>
    ) : (
        Content
    )
}
