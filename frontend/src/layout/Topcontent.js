import React, { Component } from 'react'
import api from './../lib/api';
import { Modal } from '../lib/components/Modal';

function ChangelogModal(props) {
    return <Modal onDismiss={props.onDismiss}>
        <iframe
            style={{border: 0, width: '100%', height: '80vh', margin: '0 -1rem'}}
            src="https://update.posthog.com/changelog" />
    </Modal>
}

export class Topcontent extends Component {
    constructor(props) {
        super(props)
        this.state = {};
        this.getCurrentVersion();
    }
    getCurrentVersion = () => {
        api.get('https://update.posthog.com/versions').then(versions => this.setState({latest_version: versions[0]['version']}))
    }
    openChangelog = e => {
        e.preventDefault();
        this.setState({openChangelog: true})
    }
    render() {
        let { latest_version, openChangelog } = this.state;
        return (
        	<div>
		        <div className="right-align" style={{display: 'flex', fontSize: 13}}>
                    {latest_version && <span style={{marginRight: 32}}>
                        {latest_version == this.props.user.posthog_version && <a href="#" onClick={this.openChangelog} className='text-success' style={{marginRight: 16}}>PostHog up-to-date</a>}
                        {latest_version != this.props.user.posthog_version && <a href="#" onClick={this.openChangelog} className='text-danger' style={{marginRight: 16}}>New version available</a>}
                    </span>}
                    {this.props.user.email}
		        </div>
                {openChangelog && <ChangelogModal onDismiss={() => this.setState({openChangelog: false})} />}
		    </div>
        )
    }
}
