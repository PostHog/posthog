import React, { useState } from 'react'
import { router } from 'kea-router'
import { InviteTeam } from 'lib/components/InviteTeam'
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
import { useActions, useValues } from 'kea'
import { Link } from 'lib/components/Link'
import { sceneLogic } from 'scenes/sceneLogic'

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

// to show the right page in the sidebar
const sceneOverride = {
    action: 'actions',
    funnel: 'funnels',
    editFunnel: 'funnels',
    person: 'people',
}

export default function Sidebar(props) {
    const { scene, loadingScene } = useValues(sceneLogic)
    const [inviteModalOpen, setInviteModalOpen] = useState(false)

    const { location } = useValues(router)
    const { push } = useActions(router)

    let matches = path => location.pathname.indexOf(path) > -1

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
                selectedKeys={[
                    loadingScene ? sceneOverride[loadingScene] || loadingScene : sceneOverride[scene] || scene,
                ]}
                openKeys={determineSubmenuOpen()}
                mode="inline"
            >
                <Logo />
                <Menu.Item key="trends" style={itemStyle}>
                    <RiseOutlined />
                    <span>{'Trends'}</span>
                    <Link to={'/trends'} />
                </Menu.Item>
                <Menu.Item key="dashboard" style={itemStyle}>
                    <HomeOutlined />
                    <span>{'Dashboard'}</span>
                    <Link to={'/dashboard'} />
                </Menu.Item>
                <Menu.SubMenu
                    key="events"
                    title={
                        <span style={itemStyle}>
                            <ContainerOutlined />
                            <span>{'Events'}</span>
                        </span>
                    }
                    onTitleClick={() => (location.pathname !== '/events' ? push('/events') : null)}
                >
                    <Menu.Item key="events" style={itemStyle}>
                        <ContainerOutlined />
                        <span>{'All Events'}</span>
                        <Link to={'/events'} />
                    </Menu.Item>
                    <Menu.Item key="actions" style={itemStyle}>
                        <AimOutlined />
                        <span>{'Actions'}</span>
                        <Link to={'/actions'} />
                    </Menu.Item>
                    <Menu.Item key="liveActions" style={itemStyle}>
                        <SyncOutlined />
                        <span>{'Live Actions'}</span>
                        <Link to={'/actions/live'} />
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
                    onTitleClick={() => (location.pathname !== '/people' ? push('/people') : null)}
                >
                    <Menu.Item key="people" style={itemStyle}>
                        <UserOutlined />
                        <span>{'All Users'}</span>
                        <Link to={'/people'} />
                    </Menu.Item>
                    <Menu.Item key="cohorts" style={itemStyle}>
                        <UsergroupAddOutlined />
                        <span>{'Cohorts'}</span>
                        <Link to={'/people/cohorts'} />
                    </Menu.Item>
                </Menu.SubMenu>
                <Menu.Item key="funnels" style={itemStyle}>
                    <FunnelPlotOutlined />
                    <span>{'Funnels'}</span>
                    <Link to={'/funnel'} />
                </Menu.Item>
                <Menu.Item key="paths" style={itemStyle}>
                    <ForkOutlined />
                    <span>{'Paths'}</span>
                    <Link to={'/paths'} />
                </Menu.Item>
                <Menu.Item key="setup" style={itemStyle}>
                    <SettingOutlined />
                    <span>{'Setup'}</span>
                    <Link to={'/setup'} />
                </Menu.Item>
                <Menu.Item key="invite" style={itemStyle} onClick={() => setInviteModalOpen(true)}>
                    <PlusOutlined />
                    <span>{'Invite your team'}</span>
                </Menu.Item>
            </Menu>

            <Modal visible={inviteModalOpen} footer={null} onCancel={() => setInviteModalOpen(false)}>
                <InviteTeam user={props.user} />
            </Modal>
        </Layout.Sider>
    )
}
