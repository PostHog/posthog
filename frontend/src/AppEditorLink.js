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
  }

  render() {
    const { app_urls: appUrls } = this.props.user.team
    return (
      <>
        <a
            onClick={(e) => {
                e.preventDefault();
                this.setState({ openChooseModal: true })
            }}
            href={appEditorUrl(this.props.actionId, appUrls && appUrls[0])} style={this.props.style} className={this.props.className}>
            {this.props.children}
        </a>
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
