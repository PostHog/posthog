import './InstructionsPanel.scss'
import { CardContainer } from 'scenes/ingestion/CardContainer'
import {
    AndroidInstructions,
    APIInstructions,
    ElixirInstructions,
    FlutterInstructions,
    GoInstructions,
    IOSInstructions,
    NodeInstructions,
    PHPInstructions,
    PythonInstructions,
    RNInstructions,
    RubyInstructions,
} from 'scenes/ingestion/frameworks'
import React from 'react'
import { API, MOBILE, BACKEND, WEB } from 'scenes/ingestion/constants'
import { useActions, useValues } from 'kea'
import { ingestionLogic } from 'scenes/ingestion/ingestionLogic'
import { WebInstructions } from '../frameworks/WebInstructions'

const frameworksSnippet: Record<string, React.ComponentType> = {
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
    const { index, platform, framework, frameworkString } = useValues(ingestionLogic)
    const { setFramework, setVerify, setPlatform } = useActions(ingestionLogic)

    if (platform !== WEB && !framework) {
        return <></>
    }

    const FrameworkSnippet: React.ComponentType = frameworksSnippet[framework as string] as React.ComponentType

    return (
        <div className="InstructionsPanel mb-2">
            {platform === WEB ? (
                <CardContainer
                    index={index}
                    showFooter={true}
                    onSubmit={() => setVerify(true)}
                    onBack={() => setPlatform(null)}
                >
                    <WebInstructions />
                </CardContainer>
            ) : framework === API ? (
                <CardContainer
                    index={index}
                    showFooter={true}
                    onSubmit={() => setVerify(true)}
                    onBack={() => setFramework(null)}
                >
                    <h2>{frameworkString}</h2>
                    <p className="prompt-text">
                        {
                            "Below is an easy format for capturing events using the API we've provided. Use this endpoint to send your first event!"
                        }
                    </p>
                    <FrameworkSnippet />
                </CardContainer>
            ) : (
                <CardContainer
                    index={index}
                    showFooter={true}
                    onSubmit={() => setVerify(true)}
                    onBack={() => setFramework(null)}
                >
                    <h1>{`Setup ${frameworkString}`}</h1>

                    {platform === BACKEND ? (
                        <>
                            <p className="prompt-text">
                                {`Follow the instructions below to send custom events from your ${frameworkString} backend.`}
                            </p>
                            <FrameworkSnippet />
                        </>
                    ) : null}
                    {platform === MOBILE ? <FrameworkSnippet /> : null}
                </CardContainer>
            )}
        </div>
    )
}
