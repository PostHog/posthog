import React from 'react'
import { Popover, Button, Checkbox, Badge } from 'antd'
import { userLogic } from 'scenes/userLogic'
import { useValues } from 'kea'
import { actionsModel } from '~/models/actionsModel'
import { Loading } from 'lib/utils'
import { DeploymentUnitOutlined } from '@ant-design/icons'
import { Link } from 'lib/components/Link'

function content({ user, actions }) {
    return (
        <div style={{ display: 'flex', width: '30vw', flexDirection: 'column' }}>
            <h2>Get Started</h2>
            <p>Complete these steps to learn how to use Posthog! Click on an item below to learn how to complete it</p>
            <Checkbox checked={user && user.has_events} onChange={e => console.log('changed')}>
                <Link to={'/setup'}>Install JS snippet</Link>
            </Checkbox>
            <hr style={{ height: 5, visibility: 'hidden' }} />
            <Checkbox checked={actions.length > 0} onChange={e => console.log('changed')}>
                <Link to={'/actions'}>Create an Action</Link>
            </Checkbox>
            <hr style={{ height: 5, visibility: 'hidden' }} />
            <Checkbox checked={false} onChange={e => console.log('changed')}>
                <Link to={'/trends'}>Create Trends graph</Link>
            </Checkbox>
        </div>
    )
}

export default function OnboardingWidget(props) {
    const { user } = useValues(userLogic)
    const { actions, actionsLoading } = useValues(actionsModel)

    return (
        <div>
            <Popover content={actionsLoading ? <Loading></Loading> : content({ user, actions })} trigger="click">
                <Badge count={3}>
                    <Button>
                        <DeploymentUnitOutlined></DeploymentUnitOutlined>
                    </Button>
                </Badge>
            </Popover>
        </div>
    )
}
