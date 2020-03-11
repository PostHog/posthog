import React from "react";
import { useValues } from 'kea'
import { BrowserRouter as Router, Route } from "react-router-dom";
import { ToastContainer, Slide } from 'react-toastify';
import 'react-toastify/dist/ReactToastify.css';
import "react-datepicker/dist/react-datepicker.css";
import api from "./Api";
import Events from "./Events";
import Person from "./Person";
import Sidebar from "./Sidebar";
import People from "./People";
import Actions from "./Actions";
import Action from "./Action";
import Topcontent from "./Topcontent";
import Funnel, { EditFunnel } from "./Funnel";
import Funnels from "./Funnels";
import { EditAction } from "./editor";
import ActionEvents from "./ActionEvents";
import Setup from "./Setup";
import ActionsGraph from "./ActionsGraph";
import Dashboard from "./Dashboard";
import SendEventsOverlay from "./SendEventsOverlay";
import Paths from "./Paths";
import Cohorts from "./Cohorts";
import { userLogic } from './userLogic'

function PrivateRoute ({ component: Component, ...props }) {
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

export default function App () {
    const { user } = useValues(userLogic)

    if (!user) {
        return null
    }

    return (
        <Router>
            <div className="container-fluid flex-grow-1 d-flex">
                <div className="row flex-fill flex-column flex-sm-row">
                    <Sidebar user={user} />
                    <div className="col-sm-9 col-sm-offset-3 col-md-10 col-md-offset-2 flex-grow-1 py-3 content">
                        <Topcontent user={user} />
                        <div style={{marginTop: '3rem'}}>
                            <SendEventsOverlay user={user} />
                            {user.has_events && <div>
                                <PrivateRoute path="/" exact component={Dashboard} user={user} />
                                <PrivateRoute path="/actions" exact component={Actions} user={user} />
                                <PrivateRoute path="/trends" exact component={ActionsGraph} user={user} />
                                <PrivateRoute path="/actions/live" component={ActionEvents} user={user} />
                                <PrivateRoute path="/funnel" exact component={Funnels} user={user} />
                                <PrivateRoute path="/paths" component={Paths} user={user} />
                            </div>}
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
                        </div>
                    </div>
                    <ToastContainer
                        autoClose={8000}
                        transition={Slide}
                        position='bottom-center' />
                </div>
            </div>
        </Router>
    )
}
