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
        accessRestrictionReason = 'This section is restricted to administrators.'

    const Content = (
        <>
            <div className="mt">
                <Button type="primary" danger onClick={confirmDeleteProject} className="mr-05">
                    Delete Project
                </Button>
                This will permanently delete your project plus <b>all the data and events</b> associated to it. Please
                be certain.
            </div>
        </>
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
