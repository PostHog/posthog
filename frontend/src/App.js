import React from "react";
import { BrowserRouter as Router, Route, Redirect } from "react-router-dom";
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

class PrivateRoute extends React.Component {
    constructor(props) {
        super(props)
    }

    render() {
        let Component = this.props.component;
        return this.props.user ? (
        <Route
            path={this.props.path}
            exact
            render={props => {
                if(window.posthog) posthog.capture('$pageview');
                if(this.props.user) return (<div>
                    <Component {...this.props} {...props} user={this.props.user} history={props.history} />
                </div>);
                return <Redirect
                    to={{
                        pathname: "/login",
                        state: { from: props.location }
                    }}
                    />
            }}
        />
        ) : null;
    }
}

export default class App extends React.Component {
    constructor(props) {
        super(props)

        this.state = {};
        this.getUser.call(this);
    }
    getUser() {
        api.get('api/user').then((user) => {
            this.setState({user: user});
            if(user && user.id) {
                if(window.Sentry) Sentry.setUser({"email": user.email, "id": user.id});
                if(window.posthog) posthog.identify(user.distinct_id);
            }
        }).catch(() => this.setState({user: false}));
    }

    render() {
        return this.state.user != null && (
            <Router>
                <div className="container-fluid flex-grow-1 d-flex">
                    <div className="row flex-fill flex-column flex-sm-row">
                        <Sidebar user={this.state.user} />
                        <div className="col-sm-9 col-sm-offset-3 col-md-10 col-md-offset-2 flex-grow-1 py-3 content">
                            <Topcontent user={this.state.user} />
                            <div style={{marginTop: '3rem'}}>
                                <SendEventsOverlay user={this.state.user} />
                                {this.state.user.has_events && <div>
                                    <PrivateRoute path="/" exact component={Dashboard} user={this.state.user} />
                                    <PrivateRoute path="/actions" exact component={Actions} user={this.state.user} onUpdateUser={(user) => this.setState({user})} />
                                    <PrivateRoute path="/trends" exact component={ActionsGraph} user={this.state.user} />
                                    <PrivateRoute path="/actions/live" component={ActionEvents} user={this.state.user} />
                                    <PrivateRoute path="/funnel" exact component={Funnels} user={this.state.user} />
                                    <PrivateRoute path="/paths" component={Paths} user={this.state.user} />
                                </div>}
                                <PrivateRoute path="/setup" component={Setup} user={this.state.user} onUpdateUser={(user) => this.setState({user})} />
                                <PrivateRoute path="/events" component={Events} user={this.state.user} />
                                <PrivateRoute exact path="/person_by_id/:id" component={Person} user={this.state.user} />
                                <PrivateRoute exact path="/person/:distinct_id" component={Person} user={this.state.user} />
                                <PrivateRoute path="/people" component={People} user={this.state.user} />
                                <PrivateRoute path="/people/cohorts" component={Cohorts} user={this.state.user} />
                                <PrivateRoute path="/action/:id" component={Action} user={this.state.user} />
                                <PrivateRoute path="/action" component={Action} user={this.state.user} />
                                <PrivateRoute path="/new-funnel" component={EditFunnel} user={this.state.user} />
                                <PrivateRoute path="/funnel/:id" exact component={Funnel} user={this.state.user} />
                            </div>
                        </div>
                        <ToastContainer
                            autoClose={8000}
                            transition={Slide}
                            position='bottom-center' />
                    </div>
                </div>
            </Router>
        );
    }
}
