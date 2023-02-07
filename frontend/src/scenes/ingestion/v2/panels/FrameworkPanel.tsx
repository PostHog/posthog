import { useActions, useValues } from 'kea'
import { CardContainer } from 'scenes/ingestion/v2/CardContainer'
import { ingestionLogicV2 } from '../ingestionLogicV2'
import { API, mobileFrameworks, BACKEND, webFrameworks } from 'scenes/ingestion/v2/constants'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import './Panels.scss'
import { IngestionInviteMembersButton } from '../IngestionInviteMembersButton'

export function FrameworkPanel(): JSX.Element {
    const { next } = useActions(ingestionLogicV2)
    const { platform } = useValues(ingestionLogicV2)
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
                            onClick={() => next({ framework: item })}
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
                        onClick={() => next({ framework: API })}
                    >
                        Other
                    </LemonButton>
                    <IngestionInviteMembersButton />
                </div>
            </div>
        </CardContainer>
    )
}
