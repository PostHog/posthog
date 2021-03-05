import React from 'react'
import { Card } from 'antd'
import { UserType } from '~/types'
import { PageHeader } from 'lib/components/PageHeader'
import { Invites } from './Invites'
import { Members } from './Members'

export function TeamMembers({ user }: { user: UserType }): JSX.Element {
    return (
        <>
            <PageHeader
                title="Team Members"
                caption="View and manage teammates here. Build an even better product together."
            />
            <Card>
                <Invites />
                <Members user={user} />
            </Card>
        </>
    )
}
