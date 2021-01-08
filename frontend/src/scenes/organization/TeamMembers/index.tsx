import React from 'react'
import { Card } from 'antd'
import { hot } from 'react-hot-loader/root'
import { UserType } from '~/types'
import { PageHeader } from 'lib/components/PageHeader'
import { Invites } from './Invites'
import { Members } from './Members'

export const TeamMembers = hot(_TeamMembers)
function _TeamMembers({ user }: { user: UserType }): JSX.Element {
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
