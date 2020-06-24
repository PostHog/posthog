import React, { useState } from 'react'
import { Row, List, Spin, Button } from 'antd'
import { useActions, useValues } from 'kea'
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
    APIInstructions,
    ElixirInstructions,
} from './FrameworkInstructions'
import { userLogic } from 'scenes/userLogic'
import { useInterval } from 'lib/hooks/useInterval'
import { CardContainer } from './CardContainer'

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
const ELIXIR = 'ELIXIR'
const API = 'API'

const webFrameworks = {
    [PURE_JS]: 'Javascript',
    [NODEJS]: 'NodeJS',
    [GO]: 'Go',
    [RUBY]: 'Ruby',
    [PYTHON]: 'Python',
    [PHP]: 'PHP',
    [ELIXIR]: 'Elixir',
}

const webFrameworksSnippet = {
    PURE_JS: function createJSInstructions({ user }) {
        return <JSInstructions user={user}></JSInstructions>
    },
    NODEJS: function createNodeInstructions({ user }) {
        return <NodeInstructions user={user}></NodeInstructions>
    },
    GO: function createGoInstructions({ user }) {
        return <GoInstructions user={user}></GoInstructions>
    },
    RUBY: function createRubyInstructions({ user }) {
        return <RubyInstructions user={user}></RubyInstructions>
    },
    PYTHON: function createPythonInstructions({ user }) {
        return <PythonInstructions user={user}></PythonInstructions>
    },
    PHP: function createPHPInstructions({ user }) {
        return <PHPInstructions user={user}></PHPInstructions>
    },
    ELIXIR: function createElixirInstructions({ user }) {
        return <ElixirInstructions user={user}></ElixirInstructions>
    },
}

const mobileFrameworks = {
    ANDROID: 'Android',
    IOS: 'iOS',
    REACT_NATIVE: 'React Native',
}

const mobileFrameworksSnippet = {
    ANDROID: function createAndroidInstructions({ user }) {
        return <AndroidInstructions user={user}></AndroidInstructions>
    },
    IOS: function createIOSInstructions({ user }) {
        return <IOSInstructions user={user}></IOSInstructions>
    },
    REACT_NATIVE: function createRNInstructions({ user }) {
        return <RNInstructions user={user}></RNInstructions>
    },
}

const content = {
    PLATFORM_TYPE: function CreatePlatformPanel(props) {
        return (
            <CardContainer index={0} totalSteps={4}>
                <h1>Welcome to Posthog</h1>
                <p className="prompt-text">
                    Let's get you up and running with Posthog! What type of platform is your app? (You can connect to
                    multi-deployments later)
                </p>
                <Row>
                    {platformTypes.map(type => (
                        <Button
                            type="primary"
                            data-attr={'select-platform-' + type}
                            key={type}
                            style={{ marginRight: 10 }}
                            onClick={() => props.onSubmit({ type })}
                        >
                            {type}
                        </Button>
                    ))}
                </Row>
            </CardContainer>
        )
    },
    FRAMEWORK: function CreateFrameworkPanel({ platformType, reverse, onSubmit, onApiContinue }) {
        let frameworks = {}
        if (platformType === WEB) frameworks = webFrameworks
        else if (platformType === MOBILE) frameworks = mobileFrameworks

        return (
            <CardContainer index={1} totalSteps={4} onBack={reverse}>
                <p className="prompt-text">
                    Choose the framework your app is built in. We'll provide you with snippets that you can easily add
                    to your codebase to get started!
                </p>
                <Row>
                    <List
                        style={{ width: '100%' }}
                        bordered
                        dataSource={Object.keys(frameworks)}
                        renderItem={item => (
                            <List.Item
                                className="selectable-item"
                                data-attr={'select-framework-' + item}
                                onClick={() => onSubmit({ framework: item })}
                                key={item}
                            >
                                {frameworks[item]}
                            </List.Item>
                        )}
                    ></List>
                </Row>
                <Row align="middle" style={{ float: 'right', marginTop: 8 }}>
                    Don't see a supported framework?
                    <b style={{ marginLeft: 5 }} className="clickable" onClick={() => onApiContinue()}>
                        Continue with API
                    </b>
                </Row>
            </CardContainer>
        )
    },
    INSTRUCTIONS: function CreateInstructionsPanel({ user, onSubmit, reverse, platformType, framework }) {
        return (
            <InstructionsPanel
                user={user}
                onSubmit={onSubmit}
                reverse={reverse}
                platformType={platformType}
                framework={framework}
            ></InstructionsPanel>
        )
    },
    VERIFICATION: function CreateVerificationPanel({ reverse }) {
        return <VerificationPanel reverse={reverse}></VerificationPanel>
    },
}

export default function OnboardingWizard({ user }) {
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

    function onApiContinue() {
        setFramework(API)
        setIndex(index + 1)
    }

    return (
        <div
            className="background"
            style={{ display: 'flex', height: '100vh', width: '100vw', alignItems: 'center', justifyContent: 'center' }}
        >
            {content[states[index]]({ onSubmit, platformType, user, reverse, framework, onApiContinue })}
        </div>
    )
}

function VerificationPanel({ reverse }) {
    const { loadUser, userUpdateRequest } = useActions(userLogic)
    const { user } = useValues(userLogic)

    useInterval(() => {
        !user.has_events && loadUser()
    }, 3000)

    return (
        <CardContainer index={3} totalSteps={4} onBack={reverse}>
            {!user.has_events ? (
                <>
                    <Row align="middle">
                        <Spin></Spin>
                        <h2 className="ml-3">Listening for events!</h2>
                    </Row>
                    <p className="prompt-text">
                        {' '}
                        Once you have integrated the snippet and sent an event, we will verify it sent properly and
                        continue
                    </p>
                    <b
                        data-attr="wizard-complete-button"
                        style={{ float: 'right' }}
                        className="clickable"
                        onClick={() => userUpdateRequest({ team: { completed_snippet_onboarding: true } })}
                    >
                        Continue without verifying
                    </b>
                </>
            ) : (
                <>
                    <h2>Successfully sent events!</h2>
                    <p className="prompt-text">
                        You will now be able to explore Posthog and take advantage of all its features to understand
                        your users.
                    </p>
                    <Button
                        data-attr="wizard-complete-button"
                        type="primary"
                        style={{ float: 'right' }}
                        onClick={() => userUpdateRequest({ team: { completed_snippet_onboarding: true } })}
                    >
                        Complete
                    </Button>
                </>
            )}
        </CardContainer>
    )
}

function InstructionsPanel({ user, onSubmit, reverse, platformType, framework }) {
    const [selected, setSelected] = useState(0)
    if (framework === API) {
        return (
            <CardContainer index={2} totalSteps={4} nextButton={true} onSubmit={onSubmit} onBack={reverse}>
                <h2>API</h2>
                <p className="prompt-text">
                    {
                        "Below is an easy format for capturing events using the api we've provided. Use this endpoint to send your first event!"
                    }
                </p>
                <APIInstructions user={user}></APIInstructions>
            </CardContainer>
        )
    }

    if (framework === PURE_JS) {
        return (
            <CardContainer index={2} totalSteps={4} nextButton={true} onSubmit={onSubmit} onBack={reverse}>
                <h2>Posthog-JS</h2>
                <p className="prompt-text">
                    {
                        'Posthog-JS will automatically capture page views, page leaves, and interactions with specific elements (<a>, <button>, <input>, <textarea>, <form>)'
                    }
                </p>
                {webFrameworksSnippet[framework]({ user })}
            </CardContainer>
        )
    }
    return (
        <CardContainer index={2} totalSteps={4} nextButton={true} onSubmit={onSubmit} onBack={reverse}>
            {platformType === WEB ? (
                <Row style={{ marginLeft: -5 }} justify="space-between" align="middle">
                    <h2 style={{ color: 'black', marginLeft: 8 }} onClick={() => setSelected(0)}>
                        {selected === 0 ? 'Autocapture' : 'Custom Capture'}
                    </h2>
                    <b
                        style={{ marginLeft: 5, color: '#007bff', marginBottom: 10, marginRight: 0 }}
                        className="clickable"
                        onClick={() => setSelected((selected + 1) % 2)}
                    >
                        {selected === 0
                            ? 'I also want to capture Custom Events'
                            : 'I want to automatically capture events'}
                    </b>
                </Row>
            ) : (
                <h2>Setup</h2>
            )}
            {platformType === WEB && selected === 0 && (
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
                    <h2>Send an Event</h2>
                    <p className="prompt-text">
                        {
                            "Once you've inserted the snippet, click on a button or form on your website to send an event!"
                        }
                    </p>
                </>
            )}
            {platformType === WEB && selected == 1 && (
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
