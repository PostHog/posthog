import React, { useState } from 'react'
import { useHistory, NavLink } from 'react-router-dom'
import { InviteTeam } from '../lib/components/InviteTeam'
import { Menu, Layout, Modal } from 'antd'
import {
    UserOutlined,
    ForkOutlined,
    FunnelPlotOutlined,
    SettingOutlined,
    RiseOutlined,
    HomeOutlined,
    PlusOutlined,
} from '@ant-design/icons'

const itemStyle = { display: 'flex', alignItems: 'center' }

export default function Sidebar(props) {
    let [inviteModalOpen, setInviteModalOpen] = useState(false)
    let history = useHistory()

    let matches = path => history.location.pathname.indexOf(path) > -1

    let determineSubmenuOpen = () => {
        if (matches('/action') || matches('events')) {
            return ['events']
        } else if (matches('people') || matches('/person')) {
            return ['people']
        } else {
            return []
        }
    }

    return (
        <Layout.Sider
            breakpoint="lg"
            collapsedWidth="0"
            onCollapse={(collapsed, type) => {
                props.onCollapse(collapsed, type)
            }}
        >
            <Menu
                className="h-100 bg-light"
                selectedKeys={[history.location.pathname]}
                openKeys={determineSubmenuOpen()}
                mode="inline"
            >
                <div
                    className="row logo-row d-flex align-items-center justify-content-center"
                    style={{ margin: 16, height: 32 }}
                >
                    <img
                        className="logo"
                        src="/static/posthog-logo.png"
                        style={{ maxHeight: '100%', marginRight: 10 }}
                    />
                    <div className="posthog-title" style={{ fontSize: 16 }}>
                        PostHog
                    </div>
                </div>
                <Menu.Item key={'/'} style={itemStyle}>
                    <HomeOutlined />
                    <span>{'Dashboard'}</span>
                    <NavLink className={'nav-link'} to={'/'}></NavLink>
                </Menu.Item>
                <Menu.Item key={'/trends'} style={itemStyle}>
                    <RiseOutlined />
                    <span>{'Trends'}</span>
                    <NavLink className={'nav-link'} to={'/trends'}></NavLink>
                </Menu.Item>
                <Menu.SubMenu
                    key="events"
                    title={
                        <span style={itemStyle}>
                            <HomeOutlined />
                            <span>{'Events'}</span>
                        </span>
                    }
                    onTitleClick={() => (history.location.pathname != '/events' ? history.push('/events') : null)}
                >
                    <Menu.Item key={'/events'} style={itemStyle}>
                        <HomeOutlined />
                        <span>{'All Events'}</span>
                        <NavLink className={'nav-link'} to={'/events'}></NavLink>
                    </Menu.Item>
                    <Menu.Item key={'/actions'} style={itemStyle}>
                        <HomeOutlined />
                        <span>{'Actions'}</span>
                        <NavLink className={'nav-link'} to={'/actions'}></NavLink>
                    </Menu.Item>
                    <Menu.Item key={'/actions/live'} style={itemStyle}>
                        <HomeOutlined />
                        <span>{'Live Actions'}</span>
                        <NavLink className={'nav-link'} to={'/actions/live'}></NavLink>
                    </Menu.Item>
                </Menu.SubMenu>
                <Menu.SubMenu
                    key="people"
                    title={
                        <span style={itemStyle}>
                            <UserOutlined />
                            <span>{'People'}</span>
                        </span>
                    }
                    onTitleClick={() => (history.location.pathname != '/people' ? history.push('/people') : null)}
                >
                    <Menu.Item key={'/people'} style={itemStyle}>
                        <UserOutlined />
                        <span>{'All Users'}</span>
                        <NavLink className={'nav-link'} to={'/people'}></NavLink>
                    </Menu.Item>
                    <Menu.Item key={'/people/cohorts'} style={itemStyle}>
                        <UserOutlined />
                        <span>{'Cohorts'}</span>
                        <NavLink className={'nav-link'} to={'/people/cohorts'}></NavLink>
                    </Menu.Item>
                </Menu.SubMenu>
                <Menu.Item key={'/funnel'} style={itemStyle}>
                    <FunnelPlotOutlined />
                    <span>{'Funnels'}</span>
                    <NavLink className={'nav-link'} to={'/funnel'}></NavLink>
                </Menu.Item>
                <Menu.Item key={'/paths'} style={itemStyle}>
                    <ForkOutlined />
                    <span>{'Paths'}</span>
                    <NavLink className={'nav-link'} to={'/paths'}></NavLink>
                </Menu.Item>
                <Menu.Item key={'/setup'} style={itemStyle}>
                    <SettingOutlined />
                    <span>{'Setup'}</span>
                    <NavLink className={'nav-link'} to={'/setup'}></NavLink>
                </Menu.Item>
                <Menu.Item
                    key={'invite'}
                    style={{ display: 'flex', alignItems: 'center' }}
                    onClick={() => setInviteModalOpen(true)}
                >
                    <PlusOutlined></PlusOutlined>
                    <span>{'Invite your team'}</span>
                </Menu.Item>
            </Menu>

            <Modal visible={inviteModalOpen} footer={null} onCancel={() => setInviteModalOpen(false)}>
                <InviteTeam user={props.user} />
            </Modal>
        </Layout.Sider>
    )
}
