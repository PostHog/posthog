import React, { useState } from 'react'
import { Row, List, Button } from 'antd'
import './OnboardingWizard.scss'

import { CardContainer } from './CardContainer'
import { VerificationPanel } from 'scenes/onboarding/VerificationPanel'
import { AutocapturePanel } from 'scenes/onboarding/AutocapturePanel'
import { InstructionsPanel } from 'scenes/onboarding/InstructionsPanel'
import {
    API,
    AUTOCAPTURE,
    FRAMEWORK,
    INSTRUCTIONS,
    MOBILE,
    mobileFrameworks,
    PLATFORM_TYPE,
    platformTypes,
    VERIFICATION,
    WEB,
    webFrameworks,
} from 'scenes/onboarding/constants'
import { Framework, PlatformType } from 'scenes/onboarding/types'

const states = {
    0: PLATFORM_TYPE,
    1: AUTOCAPTURE,
    2: FRAMEWORK,
    3: INSTRUCTIONS,
    4: VERIFICATION,
}

type CreatePanelParameters = {
    onSubmit: ({ type, framework }: { type?: PlatformType; framework?: Framework }) => void
    reverse: () => void
    onCustomContinue: () => void
    platformType: PlatformType
    framework: Framework
    onApiContinue: () => void
}

const content = {
    PLATFORM_TYPE: function CreatePlatformPanel({ onSubmit }: CreatePanelParameters): JSX.Element {
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
                            onClick={() => onSubmit({ type: type as PlatformType })}
                        >
                            {type}
                        </Button>
                    ))}
                </Row>
            </CardContainer>
        )
    },
    AUTOCAPTURE: function CreateAutocapturePanel({
        onSubmit,
        reverse,
        onCustomContinue,
    }: CreatePanelParameters): JSX.Element {
        return <AutocapturePanel onSubmit={onSubmit} reverse={reverse} onCustomContinue={onCustomContinue} />
    },
    FRAMEWORK: function CreateFrameworkPanel({
        platformType,
        reverse,
        onSubmit,
        onApiContinue,
    }: CreatePanelParameters): JSX.Element {
        const frameworks = platformType === WEB ? webFrameworks : mobileFrameworks

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
                        dataSource={Object.keys(frameworks) as (keyof typeof frameworks)[]}
                        renderItem={(item) => (
                            <List.Item
                                className="selectable-item"
                                data-attr={'select-framework-' + item}
                                onClick={() => onSubmit({ framework: item as Framework })}
                                key={item}
                            >
                                {frameworks[item]}
                            </List.Item>
                        )}
                    />
                </Row>
                <Row align="middle" style={{ float: 'right', marginTop: 8 }}>
                    Don't see a language/platform/framework here?
                    <b style={{ marginLeft: 5 }} className="button-border clickable" onClick={onApiContinue}>
                        Continue with our HTTP API
                    </b>
                </Row>
            </CardContainer>
        )
    },
    INSTRUCTIONS: function CreateInstructionsPanel({
        onSubmit,
        reverse,
        platformType,
        framework,
    }: CreatePanelParameters): JSX.Element {
        return (
            <InstructionsPanel
                onSubmit={onSubmit}
                reverse={reverse}
                platformType={platformType}
                framework={framework}
            />
        )
    },
    VERIFICATION: function CreateVerificationPanel({ reverse }: CreatePanelParameters) {
        return <VerificationPanel reverse={reverse} />
    },
}

export default function OnboardingWizard(): JSX.Element {
    const [index, setIndex] = useState(0)
    const [platformType, setPlatformType] = useState(null as PlatformType)
    const [framework, setFramework] = useState(null as Framework)
    const [path, setPath] = useState([] as number[])

    function onSubmit({ type, framework }: { type?: PlatformType; framework?: Framework } = {}): void {
        setPath([...path, index])
        if (index === 0 && type) {
            setPlatformType(type)
            if (type === MOBILE) {
                setIndex(index + 2)
                return
            }
        } else if (index === 1) {
            setIndex(4)
            return
        } else if (index === 2 && framework) {
            setFramework(framework)
        }
        setIndex((index + 1) % 5)
    }

    function reverse(): void {
        const copyPath = [...path]
        const prev = copyPath.pop()
        if (typeof prev !== 'undefined') {
            setIndex(prev)
        }
        setPath(copyPath)
    }

    function onApiContinue(): void {
        setPath([...path, index])
        setFramework(API)
        setIndex(index + 1)
    }

    function onCustomContinue(): void {
        setPath([...path, index])
        setIndex(2)
    }

    return (
        <div
            className="background"
            style={{ display: 'flex', height: '100vh', width: '100vw', alignItems: 'center', justifyContent: 'center' }}
        >
            {content[states[index as 0 | 1 | 2 | 3 | 4] as keyof typeof content]({
                onCustomContinue,
                onSubmit,
                platformType,
                framework: framework as Framework,
                reverse,
                onApiContinue,
            })}
        </div>
    )
}
