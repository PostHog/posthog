import React from "react";
import { BrowserRouter as Router, Route, Redirect } from "react-router-dom";
import api from "./Api";
import Events from "./Events";
import "../style/style.scss";



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
                if(window.posthog) window.posthog.track('ph_page_view');
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
                Sentry.setUser({"email": user.email, "id": user.id});
                posthog.identify(user.id);
                posthog.peopel.set({
                    "email": user.email
                })
            }

        }).catch(() => this.setState({user: false}));
    }
    render() {
        return this.state.user != null && (
            <Router>
                <div className="container-fluid flex-grow-1 d-flex">
                    <div className="row flex-fill flex-column flex-sm-row">
                        <div className="col-sm-3 col-md-2 sidebar flex-shrink-1 bg-dark pt-3" style={{minHeight: '100vh'}}>
                            <ul className="nav flex-sm-column">
                                <li className="active"><a className="nav-link" href="/">Home</a></li>
                                <li><a className="nav-link" href="../notes">Notes</a></li>
                                <li><a className="nav-link" href="../chat">Chat</a></li>
                                <li><a className="nav-link" href="../rss">RSS</a></li>
                            </ul>
                        </div>
                        <div className="col-sm-9 col-sm-offset-3 col-md-10 col-md-offset-2 flex-grow-1 py-3">
                            <PrivateRoute path="/" exact component={function() { return 'asdfrrr '}} user={this.state.user} />
                            <Route path="/events" component={Events} user={this.state.user} />
                            <Route path="/login/:signup_token?" strict={false} render={props => { trackPageView(); return <Login {...props} />}} />
                        </div>
                    </div>
                </div>
            </Router>
        );
    }
}