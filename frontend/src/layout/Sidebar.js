import React, { Component } from 'react'
import { withRouter, NavLink } from 'react-router-dom'
import { InviteTeam } from '../lib/components/InviteTeam'
import { Modal } from '../lib/components/Modal'

import { Menu } from 'antd'
class Sidebar extends Component {
    constructor(props) {
        super(props)
        this.state = {}
    }

    showSubgroup = keys => {
        let show = false
        keys.forEach(key => {
            if (this.props.history.location.pathname == key) show = true
        })
        return show
    }

    render() {
        return (
            <Menu
                className="sidebar vh-100 col-sm-3 col-md-2 flex-shrink-1 bg-light pt-3"
                selectedKeys={[this.props.history.location.pathname]}
                mode="inline"
            >
                <div className="row logo-row d-flex align-items-center">
                    <img className="logo" src="/static/posthog-logo.png" />
                    <div className="posthog-title">PostHog</div>
                </div>
                <Menu.Item {...this.props} key="/">
                    <i className="fi flaticon-home" />
                    <span className="menu-label">Dashboard</span>
                    <NavLink className="nav-link" exact to="/"></NavLink>
                </Menu.Item>
                <Menu.Item {...this.props} key="/trends">
                    <i className="fi flaticon-target" />
                    <span className="menu-label">Trends</span>
                    <NavLink className="nav-link" to="/trends"></NavLink>
                </Menu.Item>
                <Menu.Item {...this.props} key="/events">
                    <i className="fi flaticon-zoom-in" />
                    <span className="menu-label">Events</span>
                    <NavLink className="nav-link" to="/events"></NavLink>
                </Menu.Item>
                {this.showSubgroup(['/events', '/actions', '/actions/live']) && (
                    <Menu.Item className="inner-menu-item" {...this.props} key="/actions">
                        <i className="fi flaticon-target" />
                        <span className="menu-label">Actions</span>
                        <NavLink className="nav-link" to="/actions"></NavLink>
                    </Menu.Item>
                )}
                {this.showSubgroup(['/events', '/actions', '/actions/live']) && (
                    <Menu.Item className="inner-menu-item" {...this.props} key="/actions/live">
                        <i className="fi flaticon-refresh" />
                        <span className="menu-label">Live Actions</span>
                        <NavLink className="nav-link" to="/actions/live"></NavLink>
                    </Menu.Item>
                )}
                <Menu.Item {...this.props} key="/people">
                    <i className="fi flaticon-speech-bubble" />
                    <span className="menu-label">Users</span>
                    <NavLink className={'nav-link'} to="/people"></NavLink>
                </Menu.Item>
                {this.showSubgroup(['/people', '/people/cohorts']) && (
                    <Menu.Item className="inner-menu-item" {...this.props} key="/people/cohorts">
                        <i className="fi flaticon-user" />
                        <span className="menu-label">Cohorts</span>
                        <NavLink className={'nav-link'} to="/people/cohorts"></NavLink>
                    </Menu.Item>
                )}
                <Menu.Item {...this.props} key="/funnel">
                    <i className="fi flaticon-cursor-1" />
                    <span className="menu-label">Funnels</span>
                    <NavLink className={'nav-link'} to="/funnel"></NavLink>
                </Menu.Item>
                <Menu.Item {...this.props} key="/paths">
                    <i className="fi flaticon-shuffle-1" style={{ transform: 'rotate(180deg)' }} />
                    <span className="menu-label">Paths</span>
                    <NavLink className={'nav-link'} to="/paths"></NavLink>
                </Menu.Item>
                <Menu.Item {...this.props} key="/setup">
                    <i className="fi flaticon-settings" />
                    <span className="menu-label">Setup</span>
                    <NavLink className={'nav-link'} to="/setup"></NavLink>
                </Menu.Item>
                <div className="col-sm-3 col-md-2 invite-team">
                    <button className="secondary" onClick={() => this.setState({ inviteModalOpen: true })}>
                        Invite your team
                    </button>
                </div>
                {this.state.inviteModalOpen && (
                    <Modal onDismiss={() => this.setState({ inviteModalOpen: false })} hideFooter={true}>
                        <InviteTeam user={this.props.user} />
                    </Modal>
                )}
            </Menu>
        )
    }
}
export default withRouter(Sidebar)
