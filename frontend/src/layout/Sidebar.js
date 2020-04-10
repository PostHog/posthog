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

    render() {
        let matches = path => this.props.history.location.pathname.indexOf(path) > -1
        return (
            <div className="sidebar col-sm-3 col-md-2 flex-shrink-1 bg-light pt-3" style={{ minHeight: '100vh' }}>
                <Menu className="h-100 bg-light" selectedKeys={[this.props.history.location.pathname]} mode="inline">
                    <div className="row logo-row d-flex align-items-center">
                        <img className="logo" src="/static/posthog-logo.png" />
                        <div className="posthog-title">PostHog</div>
                    </div>
                    <Menu.Item key="/">
                        <i className="fi flaticon-home" />
                        <span className="menu-label">Dashboard</span>
                        <NavLink className="nav-link" exact to="/"></NavLink>
                    </Menu.Item>
                    <Menu.Item key="/trends">
                        <i className="fi flaticon-target" />
                        <span className="menu-label">Trends</span>
                        <NavLink className="nav-link" to="/trends"></NavLink>
                    </Menu.Item>
                    <Menu.Item key="/events">
                        <i className="fi flaticon-zoom-in" />
                        <span className="menu-label">Events</span>
                        <NavLink className="nav-link" to="/events"></NavLink>
                    </Menu.Item>
                    {(matches('/action') || matches('/events')) && [
                        <Menu.Item key="/actions">
                            <i className="fi flaticon-target inner-menu-icon" />
                            <span className="menu-label">Actions</span>
                            <NavLink className="nav-link" to="/actions"></NavLink>
                        </Menu.Item>,
                        <Menu.Item key="/actions/live">
                            <i className="fi flaticon-refresh inner-menu-icon" />
                            <span className="menu-label">Live Actions</span>
                            <NavLink className="nav-link" to="/actions/live"></NavLink>
                        </Menu.Item>,
                    ]}
                    <Menu.Item key="/people">
                        <i className="fi flaticon-speech-bubble" />
                        <span className="menu-label">Users</span>
                        <NavLink className={'nav-link'} to="/people"></NavLink>
                    </Menu.Item>
                    {matches('/people') && (
                        <Menu.Item key="/people/cohorts">
                            <i className="fi flaticon-user inner-menu-icon" />
                            <span className="menu-label ">Cohorts</span>
                            <NavLink className={'nav-link'} to="/people/cohorts"></NavLink>
                        </Menu.Item>
                    )}
                    <Menu.Item key="/funnel">
                        <i className="fi flaticon-cursor-1" />
                        <span className="menu-label">Funnels</span>
                        <NavLink className={'nav-link'} to="/funnel"></NavLink>
                    </Menu.Item>
                    <Menu.Item key="/paths">
                        <i className="fi flaticon-shuffle-1" style={{ transform: 'rotate(180deg)' }} />
                        <span className="menu-label">Paths</span>
                        <NavLink className={'nav-link'} to="/paths"></NavLink>
                    </Menu.Item>
                    <Menu.Item key="/setup">
                        <i className="fi flaticon-settings" />
                        <span className="menu-label">Setup</span>
                        <NavLink className={'nav-link'} to="/setup"></NavLink>
                    </Menu.Item>
                </Menu>
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
            </div>
        )
    }
}
export default withRouter(Sidebar)
