import './InstructionsPanel.scss'
import { CardContainer } from 'scenes/ingestion/v2/CardContainer'
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
} from 'scenes/ingestion/v2/frameworks'
import { API, MOBILE, BACKEND, WEB } from '../constants'
import { useValues } from 'kea'
import { ingestionLogicV2 } from '../ingestionLogicV2'
import { WebInstructions } from '../frameworks/WebInstructions'
import { Link } from '@posthog/lemon-ui'

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
    const { platform, framework, frameworkString } = useValues(ingestionLogicV2)

    if (platform !== WEB && !framework) {
        return <></>
    }

    const FrameworkSnippet: React.ComponentType = frameworksSnippet[framework as string] as React.ComponentType

    return (
        <div className="InstructionsPanel mb-8">
            {platform === WEB ? (
                <CardContainer showFooter>
                    <WebInstructions />
                </CardContainer>
            ) : framework === API ? (
                <CardContainer showFooter>
                    <h2>{frameworkString}</h2>
                    <p className="prompt-text">
                        Need a different framework? Our HTTP API is a flexible way to use PostHog anywhere. Try the
                        endpoint below to send your first event, and view our API docs{' '}
                        <Link to="https://posthog.com/docs/api">here</Link>.
                    </p>
                    <FrameworkSnippet />
                </CardContainer>
            ) : (
                <CardContainer showFooter>
                    <h1>{`Setup ${frameworkString}`}</h1>

                    {platform === BACKEND ? (
                        <>
                            <p className="prompt-text">
                                Follow the instructions below to send custom events from your {frameworkString} backend.
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
