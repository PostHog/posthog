import React, { useState } from 'react'
import { Card, Row, List, Col, Spin } from 'antd'
import './onboardingWizard.scss'
import { JSSnippet } from 'lib/components/JSSnippet'
import {
    AndroidInstructions,
    GoInstructions,
    IOSInstructions,
    NodeInstructions,
    PHPInstructions,
    PythonInstructions,
    RNInstructions,
    RubyInstructions,
    JSInstructions,
} from './FrameworkInstructions'
import { ArrowLeftOutlined } from '@ant-design/icons'

const PLATFORM_TYPE = 'PLATFORM_TYPE'
const FRAMEWORK = 'FRAMEWORK'
const INSTRUCTIONS = 'INSTRUCTIONS'
const VERIFICATION = 'VERIFICATION'

const states = {
    0: PLATFORM_TYPE,
    1: FRAMEWORK,
    2: INSTRUCTIONS,
    3: VERIFICATION,
}

const WEB = 'Web'
const MOBILE = 'Mobile'
const platformTypes = [WEB, MOBILE]

const PURE_JS = 'PURE_JS'
const NODEJS = 'NODEJS'
const GO = 'GO'
const RUBY = 'RUBY'
const PYTHON = 'PYTHON'
const PHP = 'PHP'

const webFrameworks = {
    [PURE_JS]: 'Pure Javascript',
    [NODEJS]: 'NodeJS',
    [GO]: 'Go',
    [RUBY]: 'Ruby',
    [PYTHON]: 'Python',
    [PHP]: 'PHP',
}

const webFrameworksSnippet = {
    PURE_JS: ({ user }) => <JSInstructions user={user}></JSInstructions>,
    NODEJS: ({ user }) => <NodeInstructions user={user}></NodeInstructions>,
    GO: ({ user }) => <GoInstructions user={user}></GoInstructions>,
    RUBY: ({ user }) => <RubyInstructions user={user}></RubyInstructions>,
    PYTHON: ({ user }) => <PythonInstructions user={user}></PythonInstructions>,
    PHP: ({ user }) => <PHPInstructions user={user}></PHPInstructions>,
}

const mobileFrameworks = {
    ANDROID: 'Android',
    IOS: 'iOS',
    REACT_NATIVE: 'React Native',
}

const mobileFrameworksSnippet = {
    ANDROID: ({ user }) => <AndroidInstructions user={user}></AndroidInstructions>,
    IOS: ({ user }) => <IOSInstructions user={user}></IOSInstructions>,
    REACT_NATIVE: ({ user }) => <RNInstructions user={user}></RNInstructions>,
}

const content = {
    PLATFORM_TYPE: props => (
        <CardContainer index={0} totalSteps={4}>
            <p className="prompt-text">Let's get you up and running with Posthog! What type of platform is your app?</p>
            <Row>
                {platformTypes.map(type => (
                    <div className="platform-item" key={type} onClick={() => props.onSubmit({ type })}>
                        {type}
                    </div>
                ))}
            </Row>
        </CardContainer>
    ),
    FRAMEWORK: ({ platformType, reverse, onSubmit }) => {
        let frameworks = {}
        if (platformType === WEB) frameworks = webFrameworks
        else if (platformType === MOBILE) frameworks = mobileFrameworks

        return (
            <CardContainer index={1} totalSteps={4} onBack={reverse}>
                <p className="prompt-text">Choose the framework your app is built in</p>
                <Row>
                    <List
                        style={{ width: '100%' }}
                        bordered
                        dataSource={Object.keys(frameworks)}
                        renderItem={item => (
                            <List.Item
                                className="selectable-item"
                                onClick={() => onSubmit({ framework: item })}
                                key={item}
                            >
                                {frameworks[item]}
                            </List.Item>
                        )}
                    ></List>
                </Row>
            </CardContainer>
        )
    },
    INSTRUCTIONS: ({ user, onSubmit, reverse, platformType, framework }) => (
        <InstructionsPanel
            user={user}
            onSubmit={onSubmit}
            reverse={reverse}
            platformType={platformType}
            framework={framework}
        ></InstructionsPanel>
    ),
    VERIFICATION: ({ reverse }) => <VerificationPanel reverse={reverse}></VerificationPanel>,
}

export function OnboardingWizard({ user }) {
    const [index, setIndex] = useState(0)
    const [platformType, setPlatformType] = useState(null)
    const [framework, setFramework] = useState(null)

    function onSubmit(payload) {
        if (index == 0) {
            const { type } = payload
            setPlatformType(type)
        } else if (index == 1) {
            const { framework } = payload
            setFramework(framework)
        }
        setIndex((index + 1) % 4)
    }

    function reverse() {
        setIndex(index - 1)
    }

    return (
        <div
            className="background"
            style={{ display: 'flex', height: '100vh', width: '100vw', alignItems: 'center', justifyContent: 'center' }}
        >
            {content[states[index]]({ onSubmit, platformType, user, reverse, framework })}
        </div>
    )
}

function VerificationPanel({ reverse }) {
    return (
        <CardContainer index={3} totalSteps={4} onBack={reverse}>
            <Row align="middle">
                <Spin></Spin>
                <h2 className="ml-3">Listening for events!</h2>
            </Row>
            <p className="prompt-text">
                {' '}
                Once you have integrated the snippet and sent an event, we will verify it sent properly and continue
            </p>
            <b style={{ float: 'right' }} className="back-button">
                Continue without verifying
            </b>
        </CardContainer>
    )
}

function InstructionsPanel({ user, onSubmit, reverse, platformType, framework }) {
    const [selected, setSelected] = useState(0)
    return (
        <CardContainer index={2} totalSteps={4} nextButton={true} onSubmit={onSubmit} onBack={reverse}>
            {platformType === WEB && framework !== PURE_JS ? (
                <Row style={{ marginLeft: -5 }}>
                    <h2
                        className="back-button"
                        style={{ color: selected == 0 ? 'black' : 'gray' }}
                        onClick={() => setSelected(0)}
                    >
                        Autocapture
                    </h2>
                    <h2
                        className="back-button"
                        style={{ color: selected == 1 ? 'black' : 'gray' }}
                        onClick={() => setSelected(1)}
                    >
                        Custom Capture
                    </h2>
                </Row>
            ) : (
                <h2>Setup</h2>
            )}
            {platformType === WEB && framework == PURE_JS && (
                <>
                    <p className="prompt-text">
                        {
                            'Posthog-JS will automatically capture page views, page leaves, and interactions with specific elements (<a>, <button>, <input>, <textarea>, <form>)'
                        }
                    </p>
                    {webFrameworksSnippet[framework]({ user })}
                </>
            )}

            {platformType === WEB && framework !== PURE_JS && selected === 0 && (
                <>
                    <p className="prompt-text">
                        {
                            "Since you're running a web application, we suggest using our header snippet. This snippet will automatically capture page views, page leaves, and interactions with specific elements (<a>, <button>, <input>, <textarea>, <form>) "
                        }
                    </p>
                    <p className="prompt-text">
                        {'Just insert this snippet into your website where you configure <head> or <meta> tags. '}
                    </p>
                    <JSSnippet user={user}></JSSnippet>
                </>
            )}
            {platformType === WEB && framework !== PURE_JS && selected == 1 && (
                <>
                    <p className="prompt-text">
                        {
                            'To send events from your backend or add custom events, you can use our framework specific libraries.'
                        }
                    </p>
                    {webFrameworksSnippet[framework]({ user })}
                </>
            )}
            {platformType === MOBILE && <>{mobileFrameworksSnippet[framework]({ user })}</>}
        </CardContainer>
    )
}

function CardContainer(props) {
    return (
        <Col>
            <Card
                headStyle={{ minHeight: 60 }}
                title={
                    <Row align="middle">
                        {props.index !== 0 && (
                            <ArrowLeftOutlined
                                className="back-button"
                                onClick={() => props.onBack()}
                            ></ArrowLeftOutlined>
                        )}
                        {`Step ${props.index + 1} of ${props.totalSteps}`}
                    </Row>
                }
                className="card"
                style={{ width: '65vw', maxHeight: '60vh', overflow: 'scroll' }}
            >
                {props.children}
            </Card>

            {props.nextButton && (
                <Card
                    className="card big-button"
                    style={{
                        marginTop: 20,
                        width: '65vw',
                        height: 70,
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        borderRadius: 5,
                        cursor: 'pointer',
                    }}
                    onClick={props.onSubmit}
                >
                    <span style={{ fontWeight: 500, fontSize: 18, color: 'white' }}>Continue</span>
                </Card>
            )}
        </Col>
    )
}
