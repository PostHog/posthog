import React, { useState } from 'react'
import { SwitchTransition, CSSTransition } from 'react-transition-group'
import { Card, Row, List, Col } from 'antd'
import './onboardingWizard.scss'
import { JSSnippet } from 'lib/components/JSSnippet'
import { NodeSetupSnippet, NodeInstallSnippet } from './FrameworkInstructions/node_snippet'

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

const webFrameworks = {
    PURE_JS: 'Pure Javascript',
    NODEJS: 'NodeJS',
    GO: 'Go',
    RUBY: 'Ruby',
    PYTHON: 'Python',
    PHP: 'PHP',
    ELIXIR: 'Elixir',
}

const mobileFrameworks = {
    ANDROID: 'Android',
    IOS: 'iOS',
    REACT_NATIVE: 'React Native',
}

const content = {
    PLATFORM_TYPE: props => (
        <CardContainer>
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
    FRAMEWORK: props => {
        const { platformType } = props
        let frameworks = {}
        if (platformType === WEB) frameworks = webFrameworks
        else if (platformType === MOBILE) frameworks = mobileFrameworks

        return (
            <CardContainer>
                <p className="prompt-text">Choose the framework your app is built in</p>
                <Row>
                    <List
                        style={{ width: '100%' }}
                        bordered
                        dataSource={Object.keys(frameworks)}
                        renderItem={item => (
                            <List.Item className="selectable-item" onClick={() => props.onSubmit()} key={item}>
                                {frameworks[item]}
                            </List.Item>
                        )}
                    ></List>
                </Row>
            </CardContainer>
        )
    },
    INSTRUCTIONS: ({ user, onSubmit }) => (
        <CardContainer nextButton={true} onSubmit={onSubmit}>
            <h2>Autocapture</h2>
            <p className="prompt-text">
                {
                    "Since you're running a web application, we suggest using our header snippet. This snippet will automatically capture page views, page leaves, and interactions with specific elements (<a>, <button>, <input>, <textarea>, <form>) "
                }
            </p>
            <p className="prompt-text">
                {'Just insert this snippet into your website where you configure <head> or <meta> tags. '}
            </p>
            <JSSnippet user={user}></JSSnippet>
            <h2>Custom Capture</h2>
            <p className="prompt-text">
                {'To send events from your backend or add custom events, you can use our framework specific libraries.'}
            </p>
            <h3>Install</h3>
            <NodeInstallSnippet></NodeInstallSnippet>
            <h3>Setup</h3>
            <NodeSetupSnippet user={user}></NodeSetupSnippet>
        </CardContainer>
    ),
    VERIFICATION: props => (
        <CardContainer>
            <p className="prompt-text">Listening for events!</p>
        </CardContainer>
    ),
}

export function OnboardingWizard({ user }) {
    const [index, setIndex] = useState(0)
    const [platformType, setPlatformType] = useState(null)

    function onSubmit(payload) {
        if (index == 0) {
            const { type } = payload
            setPlatformType(type)
        }
        setIndex((index + 1) % 4)
    }

    return (
        <div
            className="background"
            style={{ display: 'flex', height: '100vh', width: '100vw', alignItems: 'center', justifyContent: 'center' }}
        >
            <SwitchTransition mode={'out-in'}>
                <CSSTransition
                    key={states[index]}
                    addEndListener={(node, done) => node.addEventListener('transitionend', done, false)}
                    classNames="fade"
                >
                    {content[states[index]]({ onSubmit, platformType, user })}
                </CSSTransition>
            </SwitchTransition>
        </div>
    )
}

function CardContainer(props) {
    return (
        <Col>
            <Card className="card" style={{ width: '50vw', maxHeight: '60vh', overflow: 'scroll' }}>
                {props.children}
            </Card>

            {props.nextButton && (
                <Card
                    className="card big-button"
                    style={{
                        marginTop: 20,
                        width: '50vw',
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
