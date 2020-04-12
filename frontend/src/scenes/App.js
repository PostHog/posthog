import React, { useState } from 'react'
import { useValues } from 'kea'
import { BrowserRouter as Router, Route } from 'react-router-dom'
import { ToastContainer, Slide } from 'react-toastify'
import 'react-toastify/dist/ReactToastify.css'
import 'react-datepicker/dist/react-datepicker.css'
import { Events } from './events/Events'
import { Person } from './users/Person'
import Sidebar from '../layout/Sidebar'
import { People } from './users/People'
import { Actions } from './actions/Actions'
import { Action } from './actions/Action'
import { TopContent } from '../layout/TopContent'
import { Funnel } from './funnels/Funnel'
import { EditFunnel } from './funnels/EditFunnel'
import { Funnels } from './funnels/Funnels'
import { ActionEvents } from './actions/ActionEvents'
import { Setup } from './setup/Setup'
import { Trends } from './trends/Trends'
import { Dashboard } from './dashboard/Dashboard'
import SendEventsOverlay from '../layout/SendEventsOverlay'
import { Paths } from './paths/Paths'
import { Cohorts } from './users/Cohorts'
import { userLogic } from './userLogic'
import { Layout, Menu } from 'antd'
import {
    MenuUnfoldOutlined,
    MenuFoldOutlined,
    UserOutlined,
    VideoCameraOutlined,
    UploadOutlined,
} from '@ant-design/icons'

function PrivateRoute({ component: Component, ...props }) {
    return (
        <Route
            path={props.path}
            exact
            render={routeProps => {
                window.posthog && window.posthog.capture('$pageview')
                return <Component {...props} {...routeProps} />
            }}
        />
    )
}

export default function App() {
    const { user } = useValues(userLogic)
    const [collapsed, setCollapsed] = useState(false)

    if (!user) {
        return null
    }

    return (
        <Router>
            <Layout className="bg-white">
                <Sidebar user={user} onCollapse={(collapsed, type) => setCollapsed(collapsed)} />
                <Layout
                    className="bg-white"
                    style={{ marginLeft: collapsed ? 0 : 200, height: '100vh', width: '220px' }}
                >
                    <Layout.Header
                        className="bg-white"
                        style={{
                            background: 'white',
                            position: 'fixed',
                            zIndex: 1,
                            width: collapsed ? '100vw' : 'calc(100vw - 200px',
                        }}
                    >
                        <TopContent user={user} />
                    </Layout.Header>
                    <Layout.Content className="pl-5 pr-5 pt-3" style={{ marginTop: 64 }}>
                        <SendEventsOverlay user={user} />
                        {user.has_events && (
                            <>
                                <PrivateRoute path="/" exact component={Dashboard} user={user} />
                                <PrivateRoute path="/actions" exact component={Actions} user={user} />
                                <PrivateRoute path="/trends" exact component={Trends} user={user} />
                                <PrivateRoute path="/actions/live" component={ActionEvents} user={user} />
                                <PrivateRoute path="/funnel" exact component={Funnels} user={user} />
                                <PrivateRoute path="/paths" component={Paths} user={user} />
                            </>
                        )}
                        <PrivateRoute path="/setup" component={Setup} user={user} />
                        <PrivateRoute path="/events" component={Events} user={user} />
                        <PrivateRoute exact path="/person_by_id/:id" component={Person} user={user} />
                        <PrivateRoute exact path="/person/:distinct_id" component={Person} user={user} />
                        <PrivateRoute path="/people" component={People} user={user} />
                        <PrivateRoute path="/people/cohorts" component={Cohorts} user={user} />
                        <PrivateRoute path="/action/:id" component={Action} user={user} />
                        <PrivateRoute path="/action" component={Action} user={user} />
                        <PrivateRoute path="/new-funnel" component={EditFunnel} user={user} />
                        <PrivateRoute path="/funnel/:id" exact component={Funnel} user={user} />
                        <ToastContainer autoClose={8000} transition={Slide} position="bottom-center" />
                    </Layout.Content>
                </Layout>
            </Layout>
        </Router>
    )
}
