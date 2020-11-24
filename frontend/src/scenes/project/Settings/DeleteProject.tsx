import React from 'react'
import { useActions, useValues } from 'kea'
import { ExclamationCircleOutlined } from '@ant-design/icons'
import { red } from '@ant-design/colors'
import { Button, Tooltip } from 'antd'
import { teamLogic } from 'scenes/teamLogic'
import confirm from 'antd/lib/modal/confirm'
import { organizationLogic } from 'scenes/organizationLogic'
import { OrganizationMembershipLevel } from 'lib/constants'

export function DeleteProject(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const { deleteCurrentTeam } = useActions(teamLogic)

    function handleClick(): void {
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

    const DeleteButton = (
        <Button type="primary" danger onClick={handleClick} data-attr="delete-project-button">
            Delete Project
        </Button>
    )

    let deletionDisabledReason: string | null = null
    if ((currentOrganization?.membership_level ?? -1) < OrganizationMembershipLevel.Admin)
        deletionDisabledReason = 'You must be an organization administrator to delete projects.'

    return (
        <div>
            {deletionDisabledReason ? <Tooltip title={deletionDisabledReason}>{DeleteButton}</Tooltip> : DeleteButton}
        </div>
    )
}
