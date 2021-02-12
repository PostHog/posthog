import React, { useState } from 'react'
import { Button, Card, Input, Divider } from 'antd'
import { hot } from 'react-hot-loader/root'
import { UserType } from '~/types'
import { PageHeader } from 'lib/components/PageHeader'
import { Invites } from './Invites'
import { Members } from './Members'
import { organizationLogic } from '../../organizationLogic'
import { useActions, useValues } from 'kea'
import { DangerZone } from './DangerZone'

function DisplayName(): JSX.Element {
    const { currentOrganization, currentOrganizationLoading } = useValues(organizationLogic)
    const { renameCurrentOrganization } = useActions(organizationLogic)

    const [name, setName] = useState(currentOrganization?.name || '')

    return (
        <div>
            <h2 id="name" className="subtitle">
                Display Name
            </h2>
            <Input
                value={name}
                onChange={(event) => {
                    setName(event.target.value)
                }}
                style={{ maxWidth: '40rem', marginBottom: '1rem', display: 'block' }}
            />
            <Button
                type="primary"
                onClick={(e) => {
                    e.preventDefault()
                    renameCurrentOrganization(name)
                }}
                disabled={!name || !currentOrganization || name === currentOrganization.name}
                loading={currentOrganizationLoading}
            >
                Rename Organization
            </Button>
        </div>
    )
}

export const OrganizationSettings = hot(_OrganizationSettings)
function _OrganizationSettings({ user }: { user: UserType }): JSX.Element {
    return (
        <>
            <PageHeader
                title="Organization Settings"
                caption="View and manage your organization here. Build an even better product together."
            />
            <Card>
                <DisplayName />
                <Divider />
                <Invites />
                <Divider />
                <Members user={user} />
                <Divider />
                <DangerZone />
            </Card>
        </>
    )
}
