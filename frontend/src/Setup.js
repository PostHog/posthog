import React, { Component } from 'react'
import api from './Api';
import { JSSnippet } from './utils';

export default class Setup extends Component {
    constructor(props) {
        super(props)
    
        this.state = {
        }
    }
    render() {
        return (
            <div>
                <h1>Setup your PostHog account</h1>
                <label>What domain will you be using PostHog on?</label>
                <form onSubmit={(e) => {
                    event.preventDefault();
                    api.update('api/user', {team: {app_url: e.target.url.value}}).then(() => this.setState({saved: true}))
                    this.props.user.team.app_url = e.target.url.value;
                    this.props.onUpdateUser(this.props.user);
                }}>
                    <input defaultValue={this.props.user.team.app_url || "https://"} autoFocus style={{maxWidth: 400}} type="text" className='form-control' name='url' placeholder="https://...." />
                    <br />
                    <button className='btn btn-success' type="submit">Save url</button>
                    {this.state.saved && <p className='text-success'>URL saved.</p>}

                </form>
                <br /><br />
                <h2>Integrate PostHog</h2>
                To integrate PostHog, copy + paste the following snippet to your website. Ideally, put it just above the <pre style={{display: 'inline'}}>&lt;/head&gt;</pre> tag.
                <JSSnippet user={this.props.user} />
                <br /><br />
                <h2>Identifying users</h2>
                <p>To be able to link back which users made certain actions, you can pass through your own internal ID. Replace <pre style={{display: 'inline'}}>internal_id</pre> with your users' ID in your system.</p>
                <p>You only have to do this once per page.</p>
                <pre className='code'>
                    posthog.identify(internal_id);
                </pre>

                <br /><br />
                <h2>Pass user info</h2>
                <p>To be able to more easily see which user did certain actions, you can pass through properties from your user, like their email or full name.</p>
                <p>You could do this on each page load, or whenever a user updates their information (after account creation or on a profile update for example).</p>
                <pre className='code'>
                    {`posthog.people.set({`}<br />
                    {`    "email": user.email`}<br />
                    {`})`}
                </pre>
            </div>
        )
    }
}
