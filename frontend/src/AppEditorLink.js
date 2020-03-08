import React, { Component } from 'react';
import api from './Api';
import Modal from './Modal';
import PropTypes from 'prop-types';
import { ChooseURLModal, appEditorUrl } from './ChooseURLModal'

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
          <button
              onClick={(e) => {
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
        <a
            onClick={(e) => {
                // if (!appUrls || appUrls.length === 0 || (appUrls.length === 1 && appUrls[0] === 'https://')) {
                //     e.preventDefault();
                //     this.setState({ openAddModal: true })
                // }
                // if (appUrls.length > 1) {
                e.preventDefault();
                this.setState({ openChooseModal: true })
                // }
            }}
            href={appEditorUrl(this.props.actionId, appUrls && appUrls[0])} style={this.props.style} className={this.props.className}>
            {this.props.children}
        </a>
        {this.state.openAddModal && <this.SetURLModal />}
        {this.state.openChooseModal && (
            <ChooseURLModal
                actionId={this.props.actionId}
                appUrls={appUrls}
                setAppUrls={(appUrls) => {
                    this.props.user.team.app_urls = appUrls;
                    this.props.onUpdateUser && this.props.onUpdateUser({ ...(this.props.user) });
                }}
                dismissModal={() => this.setState({openChooseModal: false})}
            />
        )}
      </>
    )
  }
}
AppEditorLink.propTypes = {
  user: PropTypes.object.isRequired,
  actionId: PropTypes.number
}
