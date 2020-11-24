import React from 'react'
import { Card, Divider } from 'antd'
import { hot } from 'react-hot-loader/root'
import { UserType } from '~/types'
import { PageHeader } from 'lib/components/PageHeader'
import { Invites } from './Invites'
import { Members } from './Members'

export const Teammates = hot(_Teammates)
function _Teammates({ user }: { user: UserType }): JSX.Element {
    return (
        <>
            <PageHeader
                title="Teammates"
                caption="View and manage teammates here. Build an even better product together."
            />
            <Card>
                <Invites />
                <Divider />
                <Members user={user} />
            </Card>
        </>
    )
}
