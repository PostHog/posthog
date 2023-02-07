import { useActions } from 'kea'
import { ingestionLogic } from '../ingestionLogic'
import { THIRD_PARTY, platforms } from '../constants'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import './Panels.scss'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { IngestionInviteMembersButton } from '../IngestionInviteMembersButton'

export function PlatformPanel(): JSX.Element {
    const { next } = useActions(ingestionLogic)

    return (
        <div>
            <h1 className="ingestion-title">Where do you want to send events from?</h1>
            <p className="prompt-text">
                With PostHog, you can collect events from nearly anywhere. Select one to start, and you can always add
                more sources later.
            </p>
            <LemonDivider thick dashed className="my-6" />
            <div className="flex flex-col mb-6">
                {platforms.map((platform) => (
                    <LemonButton
                        key={platform}
                        fullWidth
                        center
                        size="large"
                        type="primary"
                        className="mb-2"
                        onClick={() => next({ platform })}
                    >
                        {platform}
                    </LemonButton>
                ))}
                <LemonButton
                    onClick={() => next({ platform: THIRD_PARTY })}
                    fullWidth
                    center
                    size="large"
                    className="mb-2"
                    type="primary"
                >
                    Import events from a third party
                </LemonButton>
                <IngestionInviteMembersButton />
            </div>
        </div>
    )
}
