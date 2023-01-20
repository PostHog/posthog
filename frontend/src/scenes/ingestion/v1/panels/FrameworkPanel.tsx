import { useActions, useValues } from 'kea'
import { CardContainer } from 'scenes/ingestion/v1/CardContainer'
import { ingestionLogic } from 'scenes/ingestion/v1/ingestionLogic'
import { API, mobileFrameworks, BACKEND, webFrameworks } from 'scenes/ingestion/v1/constants'
import { LemonButton } from 'lib/components/LemonButton'
import './Panels.scss'

export function FrameworkPanel(): JSX.Element {
    const { setFramework } = useActions(ingestionLogic)
    const { platform } = useValues(ingestionLogic)
    const frameworks = platform === BACKEND ? webFrameworks : mobileFrameworks

    return (
        <CardContainer>
            <div className="FrameworkPanel">
                <h1 className="ingestion-title">
                    {platform === BACKEND ? 'Choose the framework your app is built in' : 'Pick a mobile platform'}
                </h1>
                <p className="prompt-text">
                    We'll provide you with snippets that you can easily add to your codebase to get started!
                </p>
                <div>
                    {(Object.keys(frameworks) as (keyof typeof frameworks)[]).map((item) => (
                        <LemonButton
                            type="primary"
                            key={item}
                            data-attr={`select-framework-${item}`}
                            fullWidth
                            size="large"
                            center
                            className="mb-2"
                            onClick={() => setFramework(item)}
                        >
                            {frameworks[item]}
                        </LemonButton>
                    ))}
                    <div className="justify-center mt-4 pb-4">
                        <p className="text-center mb-0 text-muted text-base">
                            Don't see your framework here?{' '}
                            <a onClick={() => setFramework(API)}>
                                <b>Continue with our HTTP API</b>
                            </a>
                        </p>
                    </div>
                </div>
            </div>
        </CardContainer>
    )
}
