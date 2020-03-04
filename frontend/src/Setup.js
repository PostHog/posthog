import React, { Component } from 'react'
import api from './Api';
import { JSSnippet } from './utils';

class OptOutCapture extends Component {
    constructor(props) {
        super(props)

        this.state = {
        }
    }

    render() {
        return <div>
            PostHog uses PostHog (unsurprisingly!) to capture information about how people are using the product.
            We believe that product analytics are the best way to make PostHog more useful for everyone.<br /><br />
            We also understand there are many reasons why people don't want to or aren't allowed to send this usage data. Just tick the box below to opt out of this.<br /><br />

            <label>
                <input
                    type="checkbox"
                    onChange={(e) => {
                        api.update('api/user', {team: {opt_out_capture: e.target.checked}}).then(() => this.setState({saved: true}))
                    }}
                    defaultChecked={this.props.user.team.opt_out_capture} />
                &nbsp;Tick this box to <strong>opt-out</strong> of sending usage data to PostHog.
            </label>
            {this.state.saved && <p className='text-success'>Preference saved. <a href='/setup'>Refresh the page for the change to take effect.</a></p>}
            <br /><br />
        </div>
    }
}

export default class Setup extends Component {
    constructor(props) {
        super(props)

        this.state = {
        }
    }

    addUrl = () => {
      this.props.user.team.app_url.push('https://');
      this.props.onUpdateUser(this.props.user);
    }

    removeUrl = (index) => {
      this.props.user.team.app_url.splice(index, 1);
      this.props.onUpdateUser(this.props.user);
    }

    updateUrl = (index, value) => {
      this.props.user.team.app_url[index] = value;
      this.props.onUpdateUser(this.props.user);
    }

    onSubmit = (e) => {
      e.preventDefault();
      api.update('api/user', {team: { app_url: this.props.user.team.app_url }}).then(response => {
        this.setState({saved: true})
        this.props.user.team.app_url = response.team.app_url;
        this.props.onUpdateUser(this.props.user);
      })
    }

    render() {
        return (
            <div>
                <h1>Setup your PostHog account</h1>
                <label>What URLs will you be using PostHog on?</label>
                <form onSubmit={this.onSubmit}>
                    {(this.props.user.team.app_url || ['https://']).map((url, index) => (
                        <div key={index} style={{ marginBottom: 5 }}>
                            <input
                                defaultValue={url}
                                onChange={(e) => this.updateUrl(index, e.target.value)}
                                autoFocus
                                style={{ display: 'inline-block', maxWidth: 400 }}
                                type="url"
                                className='form-control'
                                name={`url${index}`}
                                placeholder="https://...."
                            />
                            {index > 0 ? <button className='btn btn-link' type="button" onClick={() => this.removeUrl(index)}>Remove</button> : null}
                        </div>
                    ))}
                    <button className='btn btn-link' type="button" onClick={this.addUrl} style={{ padding: '5px 0', marginBottom: 15 }}>+ Add Another URL</button>
                    <br />

                    <button className='btn btn-success' type="submit">Save URLs</button>
                    {this.state.saved && <span className='text-success' style={{ marginLeft: 10 }}>URLs saved.</span>}
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
                <br /><br />
                <h2>Opt out of capturing</h2>
                <OptOutCapture user={this.props.user} />
            </div>
        )
    }
}
