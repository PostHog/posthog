import React, { Component, useState } from 'react';
import api from './Api';
import { Link } from 'react-router-dom';
import Modal from './Modal';
import PropTypes from 'prop-types';
import { DeleteWithUndo } from './utils';

function appEditorUrl (actionId, appUrl) {
  return '/api/user/redirect_to_site/' + (actionId ? '?actionId=' + actionId : '') + (appUrl ? `${actionId ? '&' : '?'}appUrl=${encodeURIComponent(appUrl)}` : '')
}

const defaultUrl = 'https://'

function UrlRow ({ actionId, url }) {
  const [isEditing, setEditing] = useState(false)
  const [editedValue, setEditedValue] = useState(url || defaultUrl)

  return (
      <li className="list-group-item">
          {isEditing ? (
              <div key='form' style={{ display: 'flex', width: '100%' }}>
                <input
                    value={editedValue}
                    onChange={(e) => setEditedValue(e.target.value)}
                    autoFocus
                    style={{ flex: '1' }}
                    type="url"
                    className='form-control'
                    placeholder={defaultUrl}
                />
                <button className='btn btn-primary' style={{ marginLeft: 5 }} onClick={() => setEditing(false)}>Save</button>
                <button className='btn btn-outline-secondary' style={{ marginLeft: 5 }} onClick={() => { setEditing(false); setEditedValue(url || defaultUrl) }}>Cancel</button>
              </div>
          ) : typeof url === 'undefined' ? (
            <div key='add-new'>
                <a href='#' onClick={e => {e.preventDefault(); setEditing(true)}}>+ Add Another URL</a>
            </div>
          ) : (
              <div key='list'>
                  <div style={{ float: 'right' }}>
                      <button className='no-style' onClick={() => setEditing(true)}>
                          <i className='fi flaticon-edit text-primary' />
                      </button>
                      <button className='no-style text-danger'>
                          <i className='fi flaticon-basket' />
                      </button>
                  </div>
                  <a href={appEditorUrl(actionId, url)}>{url}</a>
              </div>
          )}
      </li>
  )
}

function ChooseURLModal ({ actionId, appUrls, dismissModal }) {
  return (
    <Modal title={'Which app URL shall we open?'} onDismiss={dismissModal}>
        <ul className="list-group">
            {appUrls.map((url, index) => (
                <UrlRow key={index} actionId={actionId} url={url} />
            ))}
            <UrlRow key='new' actionId={actionId} />
        </ul>
    </Modal>
  )
}

export class AppEditorLink extends Component {
    constructor(props) {
        super(props)

        this.state = {
        }
        this.SetURLModal = this.SetURLModal.bind(this);
    }
    SetURLModal() {
        return (
            <Modal title={'Set your app url'} onDismiss={() => this.setState({openAddModal: false})}>
                <label>What URL will you be using PostHog on?</label>
                <form >
                    <input defaultValue="https://" autoFocus style={{maxWidth: 400}} type="url" className='form-control' name='url' placeholder="https://...." />
                    <br />
                    <button onClick={(e) => {
                            event.preventDefault();
                            api.update('api/user', {team: {app_urls: [e.target.form.url.value]}}).then(() => {
                                this.setState({saved: true})
                            })
                            this.props.user.team.app_urls = [e.target.form.url.value];
                            window.location.href = appEditorUrl(this.props.actionId, e.target.form.url.value);
                            this.props.onUpdateUser(this.props.user);
                        }}
                        className='btn btn-success' type="submit">Save URL & go</button>
                    {this.state.saved && <p className='text-success'>URL saved</p>}
                </form>
            </Modal>
        )
    }
    render() {
        const { app_urls: appUrls } = this.props.user.team
        return (
            <>
                <a onClick={(e) => {
                    if (!appUrls || appUrls.length === 0 || (appUrls.length === 1 && appUrls[0] !== 'https://')) {
                        e.preventDefault();
                        this.setState({ openAddModal: true })
                    }
                    if (appUrls.length > 1) {
                        e.preventDefault();
                        this.setState({ openChooseModal: true })
                    }
                }}
                    href={appEditorUrl(this.props.actionId, appUrls && appUrls[0])} style={this.props.style} className={this.props.className}>
                    {this.props.children}
                </a>
                {this.state.openAddModal && <this.SetURLModal />}
                {this.state.openChooseModal && <ChooseURLModal actionId={this.props.actionId} appUrls={appUrls} dismissModal={() => this.setState({openChooseModal: false})} />}
            </>
        )
    }
}
AppEditorLink.propTypes = {
    user: PropTypes.object.isRequired,
    actionId: PropTypes.number
}

export class ActionsTable extends Component {
    constructor(props) {
        super(props)

        this.state = {
            newEvents: [],
            loading: true
        }
        this.fetchActions = this.fetchActions.bind(this);
        this.fetchActions();
    }
    fetchActions() {
        clearTimeout(this.poller)
        if(!this.state.loading) this.setState({loading: true});
        api.get('api/action/?include_count=1').then((actions) => {
            this.setState({actions: actions.results, loading: false});
        })
    }

    render() {
        let { actions, loading } = this.state;
        return (
            <div>
                <div className='btn-group float-right'>
                    <Link to='/action' className='btn btn-light'><i className='fi flaticon-add'/>&nbsp; New action</Link>
                    <AppEditorLink user={this.props.user} className='btn btn-success'><i className='fi flaticon-export' /></AppEditorLink>
                </div>
                <h1>Actions</h1>
                <p style={{maxWidth: 600}}><i>
                    Actions are PostHog’s way of easily cleaning up a large amount of Event data.
                    Actions consist of one or more events that you have decided to put into a manually-labelled bucket. They're used in Funnels, Live actions and Trends.<br /><br />
                    <a href='https://github.com/PostHog/posthog/wiki/Actions' target="_blank">See documentation</a>
                </i></p>

                <table className='table' style={{position: 'relative'}}>
                    {loading && <div className='loading-overlay'><div></div></div>}
                    <thead>
                        <tr>
                            <th scope="col">Action ID</th>
                            <th scope="col">Volume</th>
                            <th scope="col">Type</th>
                            <th></th>
                        </tr>
                    </thead>
                    <tbody>
                        {actions && actions.length == 0 && <tr><td>You don't have any actions yet.</td></tr>}
                        {actions && actions.map((action) =>
                            <tr key={action.id}>
                                <td>
                                    <Link to={'/action/' + action.id}>{action.name}</Link>
                                </td>
                                <td>{action.count}</td>
                                <td>{action.steps.map((step) =>
                                    <div key={step.id}>
                                        {(() => {
                                            switch (step.event) {
                                                case '$autocapture':    return 'Autocapture';
                                                case '$pageview':       return 'URL matches ' + step.url;
                                                default:                return 'Event: ' + step.event
                                            }
                                        })()}
                                    </div>)}
                                </td>
                                <td style={{fontSize: 16}}>
                                    <Link to={'/action/' + action.id}><i className='fi flaticon-edit' /></Link>
                                    <DeleteWithUndo
                                        endpoint="action"
                                        object={action}
                                        className='text-danger'
                                        style={{marginLeft: 8}}
                                        callback={this.fetchActions}>
                                        <i className='fi flaticon-basket' />
                                    </DeleteWithUndo>
                                </td>
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
