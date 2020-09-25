import React, { useState } from 'react'
import { Row, List, Button } from 'antd'
import './onboardingWizard.scss'

import { CardContainer } from './CardContainer'
import { VerificationPanel } from 'scenes/onboarding/VerificationPanel'
import { AutocapturePanel } from 'scenes/onboarding/AutocapturePanel'
import { InstructionsPanel } from 'scenes/onboarding/InstructionsPanel'
import {
    ANDROID,
    API,
    AUTOCAPTURE,
    ELIXIR,
    FLUTTER,
    FRAMEWORK,
    GO,
    INSTRUCTIONS,
    IOS,
    MOBILE,
    NODEJS,
    PHP,
    PLATFORM_TYPE,
    platformTypes,
    PURE_JS,
    PYTHON,
    REACT_NATIVE,
    RUBY,
    VERIFICATION,
    WEB,
} from 'scenes/onboarding/constants'

const states = {
    0: PLATFORM_TYPE,
    1: AUTOCAPTURE,
    2: FRAMEWORK,
    3: INSTRUCTIONS,
    4: VERIFICATION,
}

const webFrameworks = {
    [PURE_JS]: 'JavaScript',
    [NODEJS]: 'Node.js',
    [GO]: 'Go',
    [RUBY]: 'Ruby',
    [PYTHON]: 'Python',
    [PHP]: 'PHP',
    [ELIXIR]: 'Elixir',
}

const mobileFrameworks = {
    [ANDROID]: 'Android',
    [IOS]: 'iOS',
    [REACT_NATIVE]: 'React Native',
    [FLUTTER]: 'Flutter',
}

const content = {
    PLATFORM_TYPE: function CreatePlatformPanel(props) {
        return (
            <CardContainer index={0}>
                <h1>Welcome to PostHog</h1>
                <p className="prompt-text">
                    Let's get you up and running with PostHog! What type of platform is your app? (You can connect to
                    multi-deployments later)
                </p>
                <Row>
                    {platformTypes.map((type) => (
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
    AUTOCAPTURE: function CreateAutocapturePanel({ user, onSubmit, reverse, onCustomContinue }) {
        return (
            <AutocapturePanel user={user} onSubmit={onSubmit} reverse={reverse} onCustomContinue={onCustomContinue} />
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
                        renderItem={(item) => (
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
                    Don't see a language/platform/framework here?
                    <b style={{ marginLeft: 5 }} className="button-border clickable" onClick={() => onApiContinue()}>
                        Continue with our HTTP API
                    </b>
                </Row>
            </CardContainer>
        )
    },
    INSTRUCTIONS: function CreateInstructionsPanel({ onSubmit, reverse, platformType, framework }) {
        return (
            <InstructionsPanel
                onSubmit={onSubmit}
                reverse={reverse}
                platformType={platformType}
                framework={framework}
            ></InstructionsPanel>
        )
    },
    VERIFICATION: function CreateVerificationPanel({ reverse }) {
        return <VerificationPanel reverse={reverse} />
    },
}

export default function OnboardingWizard({ user }) {
    const [index, setIndex] = useState(0)
    const [platformType, setPlatformType] = useState(null)
    const [framework, setFramework] = useState(null)
    const [path, setPath] = useState([])

    function onSubmit(payload) {
        setPath([...path, index])
        if (index === 0) {
            const { type } = payload
            setPlatformType(type)
            if (type === MOBILE) {
                setIndex(index + 2)
                return
            }
        } else if (index === 1) {
            setIndex(4)
            return
        } else if (index === 2) {
            const { framework } = payload
            setFramework(framework)
        }
        setIndex((index + 1) % 5)
    }

    function reverse() {
        let copyPath = [...path]
        const prev = copyPath.pop()
        setIndex(prev)
        setPath(copyPath)
    }

    function onApiContinue() {
        setPath([...path, index])
        setFramework(API)
        setIndex(index + 1)
    }

    function onCustomContinue() {
        setPath([...path, index])
        setIndex(2)
    }

    return (
        <div
            className="background"
            style={{ display: 'flex', height: '100vh', width: '100vw', alignItems: 'center', justifyContent: 'center' }}
        >
            {content[states[index]]({
                onCustomContinue,
                onSubmit,
                platformType,
                user,
                reverse,
                framework,
                onApiContinue,
            })}
        </div>
    )
}
