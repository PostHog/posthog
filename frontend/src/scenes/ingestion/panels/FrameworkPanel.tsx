import './Panels.scss'

import { useActions, useValues } from 'kea'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { CardContainer } from 'scenes/ingestion/CardContainer'
import { API, BACKEND, mobileFrameworks, webFrameworks } from 'scenes/ingestion/constants'

import { IngestionInviteMembersButton } from '../IngestionInviteMembersButton'
import { ingestionLogic } from '../ingestionLogic'

export function FrameworkPanel(): JSX.Element {
    const { next } = useActions(ingestionLogic)
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
