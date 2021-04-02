import React from 'react'
import { useActions, useValues } from 'kea'
import { CardContainer } from 'scenes/ingestion/CardContainer'
import { Avatar, List, Row, Tabs, Typography } from 'antd'

import { Framework } from 'scenes/ingestion/types'
import { ingestionLogic } from 'scenes/ingestion/ingestionLogic'
import {
    clientFrameworks,
    logos,
    mobileFrameworks,
    popularFrameworks,
    webFrameworks,
    frameworkToPlatform,
} from 'scenes/ingestion/constants'
import './FrameworkPanel2.scss'

const { TabPane } = Tabs
const { Paragraph } = Typography

// console.log(displayedTab)
function FrameworksContainer(frameworks: Framework[], sort?: boolean): JSX.Element {
    // const [displayedTab, setDisplayedTab] = useState('popular')

    const { setPlatform, setFramework } = useActions(ingestionLogic)
    // const {platform, index, totalSteps} = useValues(ingestionLogic)

    // const [displayedPlatform, setDisplayedPlatform] = useState('popular')

    const getDisplayName = (item: string): string => {
        if (item === 'PURE_JS') {
            return 'JAVASCRIPT SDK'
        } else if (item === 'AUTOCAPTURE') {
            return 'Auto Capture (JS Snippet)'
        } else if (item === 'NODEJS') {
            return 'NODE JS'
        } else {
            return frameworks[item]
        }
    }

    const getDataSource = (sorted?: boolean): (keyof typeof frameworks)[] => {
        if (sorted) {
            return Object.keys(frameworks).sort((k1, k2) => {
                return getDisplayName(k1).toString().localeCompare(getDisplayName(k2).toString())
            }) as (keyof typeof frameworks)[]
        } else {
            return Object.keys(frameworks) as (keyof typeof frameworks)[]
        }
    }

    return (
        <List
            style={{ height: 350, maxHeight: 350, overflowY: 'scroll' }}
            grid={{}}
            size={'large'}
            dataSource={getDataSource(sort)}
            renderItem={(item) => (
                <List.Item
                    className="selectable-item"
                    data-attr={'select-framework-' + item}
                    key={item}
                    onClick={() => {
                        console.log('handling click')
                        console.log(item)
                        setPlatform(frameworkToPlatform(item))
                        setFramework(item)
                    }}
                >
                    {/*{item === 'PURE_JS' ? <Tag color="green">AUTO TRACK</Tag> : null}*/}
                    <div className="framework-container">
                        <div className={'logo-container'}>
                            <Avatar
                                size={64}
                                shape={
                                    item === 'PURE_JS' ||
                                    item === 'AUTOCAPTURE' ||
                                    item === 'REACT_NATIVE' ||
                                    item === 'PHP'
                                        ? 'circle'
                                        : 'square'
                                }
                                className={'logo'}
                                src={item in logos ? logos[item] : logos['default']}
                            />
                        </div>
                        <Paragraph className="framework-name" type="secondary" strong>
                            {getDisplayName(item)}
                        </Paragraph>
                    </div>
                </List.Item>
            )}
        />
    )
}

function MenuHeader(): JSX.Element {
    // const allFrameworks = Object.assign({}, webFrameworks, mobileFrameworks, clientFrameworks)
    // const mobile

    // const allFrameworksSorted = Object.values(allFrameworks).sort().reduce(
    //   (obj, key) => {
    //     obj[key] = allFrameworks[key];
    //     return obj;
    //   },
    //   {}
    // );

    return (
        <Tabs defaultActiveKey="popular">
            <TabPane tab="Most Popular" key="popular">
                {FrameworksContainer(popularFrameworks, false)}
            </TabPane>
            <TabPane tab="Browser" key="browser">
                {FrameworksContainer(clientFrameworks, true)}
            </TabPane>
            <TabPane tab="Server" key="server">
                {FrameworksContainer(webFrameworks, true)}
            </TabPane>
            <TabPane tab="Mobile" key="mobile">
                {FrameworksContainer(mobileFrameworks, true)}
            </TabPane>
            <TabPane tab="All" key="all">
                {FrameworksContainer({ ...clientFrameworks, ...webFrameworks, ...mobileFrameworks }, true)}
            </TabPane>
        </Tabs>
    )
}

export function FrameworkPanel2(): JSX.Element {
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
            <p className="prompt-text">
                Choose the framework your app is built in. We'll provide you with snippets that you can easily add to
                your codebase to get started!
            </p>

            <Row>{MenuHeader()}</Row>
        </CardContainer>
    )
}
