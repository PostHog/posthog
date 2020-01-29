import React, { Component } from 'react';
import api from './Api';
import { Link } from 'react-router-dom';
import Modal from './Modal';
import PropTypes from 'prop-types';

export class AppEditorLink extends Component {
    constructor(props) {
        super(props)
    
        this.state = {
        }
        this.SetURLModal = this.SetURLModal.bind(this);
    }

    appEditorUrl(user) {
        return user.team.app_url + '#state=' + encodeURIComponent(JSON.stringify({'action': 'mpeditor', token: user.team.api_token}));
    }
    SetURLModal() {
        return <Modal title={'Set your app url'}>
            <label>What URL will you be using PostHog on?</label>
            <form >
                <input defaultValue="https://" autoFocus style={{maxWidth: 400}} type="text" className='form-control' name='url' placeholder="https://...." />
                <br />
                <button onClick={(e) => {
                        event.preventDefault();
                        api.update('api/user', {team: {app_url: e.target.form.url.value}}).then(() => {
                            this.setState({saved: true})
                        })
                        this.props.user.team.app_url = e.target.form.url.value;
                        window.open(this.appEditorUrl(this.props.user), '_blank');
                        this.props.onUpdateUser(this.props.user);
                    }}
                    className='btn btn-success' type="submit">Save URL & go</button>
                {this.state.saved && <p className='text-success'>URL saved</p>}

            </form>
        </Modal>
    }
    render() {
        return [<a
            onClick={(e) => {
                if(this.props.user.team.app_url) return null;
                e.preventDefault();
                this.setState({openModal: true})

            }}
            href={this.appEditorUrl(this.props.user)} target="_blank" className={this.props.className}>
            {this.props.children}
        </a>,
        this.state.openModal && <this.SetURLModal />]
    }
}
AppEditorLink.propTypes = {
    user: PropTypes.object.isRequired
}

export class ActionsTable extends Component {
    constructor(props) {
        super(props)
    
        this.state = {
            newEvents: []
        }
        this.fetchEvents = this.fetchEvents.bind(this);
        this.fetchEvents();
    }
    fetchEvents() {
        clearTimeout(this.poller)
        api.get('api/action').then((actions) => {
            this.setState({actions: actions.results});
        })
    }
    
    render() {
        return (
            <div>
                <AppEditorLink user={this.props.user} className='btn btn-outline-success float-right'><i className='fi flaticon-add'/>&nbsp;&nbsp;New action&nbsp;<i className='fi flaticon-export' /></AppEditorLink>
                <h1>Actions</h1>
                <table className='table'>
                    <thead>
                        <tr>
                            <th scope="col">Action ID</th>
                            <th scope="col"># of events</th>
                        </tr>
                    </thead>
                    <tbody>
                        {this.state.actions && this.state.actions.map((action) => 
                            <tr key={action.id}>
                                <td>
                                    <Link to={'/action/' + action.id}>{action.name}</Link>
                                </td>
                                <td>{action.count}</td>
                                {/* <td>{moment(event.timestamp).fromNow()}</td> */}
                            </tr>
                        )}
                    </tbody>
                </table>
            </div>

        )
    }
}

export default class Actions extends Component {
    constructor(props) {
        super(props)
    }
    render() {
        return <ActionsTable {...this.props} />
    }
}
