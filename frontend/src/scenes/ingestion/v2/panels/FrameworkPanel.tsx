import { useActions, useValues } from 'kea'
import { CardContainer } from 'scenes/ingestion/v2/CardContainer'
import { ingestionLogic } from '../ingestionLogic'
import { API, mobileFrameworks, BACKEND, webFrameworks } from 'scenes/ingestion/v2/constants'
import { LemonButton } from 'lib/components/LemonButton'
import './Panels.scss'
import { IngestionInviteMembersButton } from '../IngestionInviteMembersButton'

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
                    <LemonButton
                        type="primary"
                        data-attr={`select-framework-api`}
                        fullWidth
                        size="large"
                        center
                        className="mb-2"
                        onClick={() => setFramework(API)}
                    >
                        Other
                    </LemonButton>
                    <IngestionInviteMembersButton />
                </div>
            </div>
        </CardContainer>
    )
}
