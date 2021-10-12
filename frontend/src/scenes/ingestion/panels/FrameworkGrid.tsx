import React from 'react'
import { useActions, useValues } from 'kea'
import { CardContainer } from 'scenes/ingestion/CardContainer'
import { Avatar, List, Row, Tabs, Tag, Typography } from 'antd'

import { Framework } from 'scenes/ingestion/types'
import { ingestionLogic } from 'scenes/ingestion/ingestionLogic'
import {
    clientFrameworks,
    logos,
    mobileFrameworks,
    webFrameworks,
    frameworkToPlatform,
    API,
} from 'scenes/ingestion/constants'
import './FrameworkGrid.scss'

const { TabPane } = Tabs
const { Paragraph } = Typography

// Helper function - getDisplayName modifies some framework names to be better suited to tiles.
const getDisplayName = (frameworks: Record<string, string>, item: Framework | string): string => {
    if (item?.toString() === 'PURE_JS') {
        return 'JAVASCRIPT'
    } else if (item?.toString() === 'AUTOCAPTURE') {
        return 'Code Snippet (HTML TAG)'
    } else if (item?.toString() === 'NODEJS') {
        return 'NODE JS'
    } else {
        return item ? frameworks[item] : ''
    }
}

// Helper function - getDataSource returns an optionally sorted list of frameworks (by value)
const getDataSource = (frameworks: Record<string, string>, sorted?: boolean): string[] => {
    if (sorted) {
        return Object.keys(frameworks).sort((k1, k2) => {
            return getDisplayName(frameworks, k1).toString().localeCompare(getDisplayName(frameworks, k2).toString())
        }) as (keyof typeof frameworks)[]
    } else {
        return Object.keys(frameworks) as (keyof typeof frameworks)[]
    }
}

function TabContents(frameworks: Record<string, string>, sort?: boolean): JSX.Element {
    const { setPlatform, setFramework } = useActions(ingestionLogic)
    const { activeTab } = useValues(ingestionLogic)

    return (
        <List
            style={{ height: 300, maxHeight: 300, overflowY: 'auto' }}
            grid={{}}
            size={'large'}
            dataSource={getDataSource(frameworks, sort) as Framework[]}
            renderItem={(item: Framework) => (
                <List.Item
                    className="selectable-item"
                    data-attr={'select-framework-' + item}
                    key={item}
                    onClick={() => {
                        setPlatform(frameworkToPlatform(item))
                        setFramework(item)
                    }}
                >
                    <div className="framework-container">
                        <div className={'logo-container'}>
                            <Avatar
                                size={64}
                                shape={'square'}
                                className={'logo'}
                                src={item && item in logos ? logos[item] : logos['default']}
                            />
                        </div>
                        <Paragraph className="framework-name" type="secondary" strong>
                            {getDisplayName(frameworks, item)}{' '}
                            {item?.toString() === 'AUTOCAPTURE' && activeTab !== 'all' && (
                                <Tag color="success">Recommended</Tag>
                            )}
                        </Paragraph>
                    </div>
                </List.Item>
            )}
        />
    )
}

function FrameworkTabs(): JSX.Element {
    const { activeTab } = useValues(ingestionLogic)
    const { setActiveTab } = useActions(ingestionLogic)

    return (
        <Tabs defaultActiveKey="browser" activeKey={activeTab} onChange={(activeKey) => setActiveTab(activeKey)}>
            <TabPane tab="Web" key="browser">
                {TabContents(clientFrameworks, true)}
            </TabPane>
            <TabPane tab="Backend" key="server">
                {TabContents(webFrameworks, true)}
            </TabPane>
            <TabPane tab="Mobile" key="mobile">
                {TabContents(mobileFrameworks, true)}
            </TabPane>
            <TabPane tab="All" key="all">
                {TabContents({ ...clientFrameworks, ...webFrameworks, ...mobileFrameworks }, true)}
            </TabPane>
        </Tabs>
    )
}

export function FrameworkGrid(): JSX.Element {
    const { setPlatform, setFramework } = useActions(ingestionLogic)
    const { index, totalSteps } = useValues(ingestionLogic)

    return (
        <CardContainer
            index={index}
            totalSteps={totalSteps}
            onBack={() => {
                setPlatform(null)
                setFramework(null)
            }}
        >
            <h1>Welcome to PostHog</h1>
            <h3>
                Choose the framework your app is built in. We'll provide you with snippets that you can easily add to
                your codebase to get started!
            </h3>

            <Row>{FrameworkTabs()}</Row>
            <Row align="middle" style={{ float: 'right', marginTop: 5 }}>
                Don't see a language/platform/framework here?
                <b
                    style={{ marginLeft: 5 }}
                    className="button-border clickable"
                    onClick={() => {
                        setPlatform(frameworkToPlatform(API))
                        setFramework(API)
                    }}
                >
                    Continue with our HTTP API
                </b>
            </Row>
        </CardContainer>
    )
}
