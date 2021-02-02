import { CardContainer } from 'scenes/ingestion/CardContainer'
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
} from 'scenes/ingestion/frameworks'
import { Row } from 'antd'
import React from 'react'
import { API, MOBILE, BACKEND } from 'scenes/ingestion/constants'
import { useActions, useValues } from 'kea'
import { ingestionLogic } from 'scenes/ingestion/ingestionLogic'

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
    const { index, totalSteps, platform, framework } = useValues(ingestionLogic)
    const { setFramework, setVerify } = useActions(ingestionLogic)

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

    return (
        <CardContainer
            index={index}
            totalSteps={totalSteps}
            nextButton={true}
            onSubmit={() => setVerify(true)}
            onBack={() => setFramework(null)}
        >
            {platform === BACKEND ? (
                <Row style={{ marginLeft: -5 }} justify="space-between" align="middle">
                    <h2 style={{ color: 'black', marginLeft: 8 }}>{'Custom Capture'}</h2>
                </Row>
            ) : (
                <h2>Setup</h2>
            )}
            {platform === BACKEND ? (
                <>
                    <p className="prompt-text">
                        {
                            'To send events from your backend or add custom events, you can use our framework specific libraries.'
                        }
                    </p>
                    <FrameworkSnippet />
                </>
            ) : null}
            {platform === MOBILE ? <FrameworkSnippet /> : null}
        </CardContainer>
    )
}
