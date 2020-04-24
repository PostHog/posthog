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
    SyncOutlined,
    AimOutlined,
    UsergroupAddOutlined,
    ContainerOutlined,
} from '@ant-design/icons'

const itemStyle = { display: 'flex', alignItems: 'center' }

function Logo() {
    return (
        <div
            className="row logo-row d-flex align-items-center justify-content-center"
            style={{ margin: 16, height: 42 }}
        >
            <img className="logo" src="/static/posthog-logo.png" style={{ maxHeight: '100%' }} />
            <div className="posthog-title">PostHog</div>
        </div>
    )
}

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
        <Layout.Sider breakpoint="lg" collapsedWidth="0" className="bg-light">
            <Menu
                className="h-100 bg-light"
                selectedKeys={[history.location.pathname]}
                openKeys={determineSubmenuOpen()}
                mode="inline"
            >
                <Logo></Logo>
                <Menu.Item key={'/trends'} style={itemStyle}>
                    <RiseOutlined />
                    <span>{'Trends'}</span>
                    <NavLink to={'/trends'}></NavLink>
                </Menu.Item>
                <Menu.Item key={'/dashboard'} style={itemStyle}>
                    <HomeOutlined />
                    <span>{'Dashboard'}</span>
                    <NavLink to={'/dashboard'}></NavLink>
                </Menu.Item>
                <Menu.SubMenu
                    key="events"
                    title={
                        <span style={itemStyle}>
                            <ContainerOutlined />
                            <span>{'Events'}</span>
                        </span>
                    }
                    onTitleClick={() => (history.location.pathname != '/events' ? history.push('/events') : null)}
                >
                    <Menu.Item key={'/events'} style={itemStyle}>
                        <ContainerOutlined />
                        <span>{'All Events'}</span>
                        <NavLink to={'/events'}></NavLink>
                    </Menu.Item>
                    <Menu.Item key={'/actions'} style={itemStyle}>
                        <AimOutlined />
                        <span>{'Actions'}</span>
                        <NavLink to={'/actions'}></NavLink>
                    </Menu.Item>
                    <Menu.Item key={'/actions/live'} style={itemStyle}>
                        <SyncOutlined />
                        <span>{'Live Actions'}</span>
                        <NavLink to={'/actions/live'}></NavLink>
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
                        <NavLink to={'/people'}></NavLink>
                    </Menu.Item>
                    <Menu.Item key={'/people/cohorts'} style={itemStyle}>
                        <UsergroupAddOutlined />
                        <span>{'Cohorts'}</span>
                        <NavLink to={'/people/cohorts'}></NavLink>
                    </Menu.Item>
                </Menu.SubMenu>
                <Menu.Item key={'/funnel'} style={itemStyle}>
                    <FunnelPlotOutlined />
                    <span>{'Funnels'}</span>
                    <NavLink to={'/funnel'}></NavLink>
                </Menu.Item>
                <Menu.Item key={'/paths'} style={itemStyle}>
                    <ForkOutlined />
                    <span>{'Paths'}</span>
                    <NavLink to={'/paths'}></NavLink>
                </Menu.Item>
                <Menu.Item key={'/setup'} style={itemStyle}>
                    <SettingOutlined />
                    <span>{'Setup'}</span>
                    <NavLink to={'/setup'}></NavLink>
                </Menu.Item>
                <Menu.Item key={'invite'} style={itemStyle} onClick={() => setInviteModalOpen(true)}>
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
