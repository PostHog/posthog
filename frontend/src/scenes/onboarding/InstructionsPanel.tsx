import { CardContainer } from 'scenes/onboarding/CardContainer'
import {
    AndroidInstructions,
    APIInstructions,
    ElixirInstructions,
    FlutterInstructions,
    GoInstructions,
    IOSInstructions,
    JSInstructions,
    NodeInstructions,
    PHPInstructions,
    PythonInstructions,
    RNInstructions,
    RubyInstructions,
} from 'scenes/onboarding/FrameworkInstructions'
import { Row } from 'antd'
import React from 'react'
import { API, MOBILE, PURE_JS, WEB } from 'scenes/onboarding/constants'
import { useActions, useValues } from 'kea'
import { onboardingLogic } from 'scenes/onboarding/onboardingLogic'

const frameworksSnippet = {
    PURE_JS: JSInstructions,
    NODEJS: NodeInstructions,
    GO: GoInstructions,
    RUBY: RubyInstructions,
    PYTHON: PythonInstructions,
    PHP: PHPInstructions,
    ELIXIR: ElixirInstructions,
    ANDROID: AndroidInstructions,
    IOS: IOSInstructions,
    REACT_NATIVE: RNInstructions,
    FLUTTER: FlutterInstructions,
    API: APIInstructions,
}

export function InstructionsPanel(): JSX.Element {
    const { index, totalSteps, platformType, framework } = useValues(onboardingLogic)
    const { setFramework, setVerify } = useActions(onboardingLogic)

    if (!framework) {
        return <></>
    }

    const FrameworkSnippet = frameworksSnippet[framework]

    if (framework === API) {
        return (
            <CardContainer
                index={index}
                totalSteps={totalSteps}
                nextButton={true}
                onSubmit={() => setVerify(true)}
                onBack={() => setFramework(null)}
            >
                <h2>API</h2>
                <p className="prompt-text">
                    {
                        "Below is an easy format for capturing events using the API we've provided. Use this endpoint to send your first event!"
                    }
                </p>
                <FrameworkSnippet />
            </CardContainer>
        )
    }

    if (framework === PURE_JS) {
        return (
            <CardContainer
                index={index}
                totalSteps={totalSteps}
                nextButton={true}
                onSubmit={() => setVerify(true)}
                onBack={() => setFramework(null)}
            >
                <h2>posthog-js</h2>
                <p className="prompt-text">
                    {
                        'posthog-js will automatically capture page views, page leaves, and interactions with specific elements (<a>, <button>, <input>, <textarea>, <form>)'
                    }
                </p>
                <FrameworkSnippet />
            </CardContainer>
        )
    }

    return (
        <CardContainer
            index={index}
            totalSteps={totalSteps}
            nextButton={true}
            onSubmit={() => setVerify(true)}
            onBack={() => setFramework(null)}
        >
            {platformType === WEB ? (
                <Row style={{ marginLeft: -5 }} justify="space-between" align="middle">
                    <h2 style={{ color: 'black', marginLeft: 8 }}>{'Custom Capture'}</h2>
                </Row>
            ) : (
                <h2>Setup</h2>
            )}
            {platformType === WEB ? (
                <>
                    <p className="prompt-text">
                        {
                            'To send events from your backend or add custom events, you can use our framework specific libraries.'
                        }
                    </p>
                    <FrameworkSnippet />
                </>
            ) : null}
            {platformType === MOBILE ? <FrameworkSnippet /> : null}
        </CardContainer>
    )
}
