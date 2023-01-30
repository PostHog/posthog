import './InstructionsPanel.scss'
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
} from 'scenes/ingestion/v1/frameworks'
import { API, MOBILE, BACKEND, WEB } from 'scenes/ingestion/v1/constants'
import { useValues } from 'kea'
import { ingestionLogic } from 'scenes/ingestion/v1/ingestionLogic'
import { WebInstructions } from '../frameworks/WebInstructions'
import { PanelFooterToRecordingStep } from 'scenes/ingestion/v1/panels/PanelComponents'

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
    const { platform, framework, frameworkString } = useValues(ingestionLogic)

    if (platform !== WEB && !framework) {
        return <></>
    }

    const FrameworkSnippet: React.ComponentType = frameworksSnippet[framework as string] as React.ComponentType

    return (
        <div className="InstructionsPanel mb-8">
            {platform === WEB ? (
                <div style={{ maxWidth: 800 }}>
                    <WebInstructions />
                    <PanelFooterToRecordingStep />
                </div>
            ) : framework === API ? (
                <div style={{ maxWidth: 800 }}>
                    <h2>{frameworkString}</h2>
                    <p className="prompt-text">
                        {
                            "Below is an easy format for capturing events using the API we've provided. Use this endpoint to send your first event!"
                        }
                    </p>
                    <FrameworkSnippet />
                    <PanelFooterToRecordingStep />
                </div>
            ) : (
                <div style={{ maxWidth: 800 }}>
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
                    <PanelFooterToRecordingStep />
                </div>
            )}
        </div>
    )
}
