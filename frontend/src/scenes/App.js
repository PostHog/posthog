import React, { useState } from 'react'
import { useValues } from 'kea'
import { BrowserRouter as Router, Route, Redirect, Switch } from 'react-router-dom'
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
import { Layout } from 'antd'

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

    if (!user) {
        return null
    }

    return (
        <Router path="/">
            <Switch>
                <Redirect exact from="/" to="/trends" />
            </Switch>
            <Layout className="bg-white">
                <Sidebar user={user} />
                <Layout className="bg-white" style={{ height: '100vh' }}>
                    <div className="content py-3">
                        <TopContent user={user} />
                    </div>
                    <Layout.Content className="pl-5 pr-5 pt-3">
                        <SendEventsOverlay user={user} />
                        {user.has_events && (
                            <>
                                <PrivateRoute path="/dashboard" exact component={Dashboard} user={user} />
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
