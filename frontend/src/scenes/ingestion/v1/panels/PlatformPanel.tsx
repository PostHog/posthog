import { useActions } from 'kea'
import { ingestionLogic } from 'scenes/ingestion/v1/ingestionLogic'
import { THIRD_PARTY, BOOKMARKLET, platforms } from 'scenes/ingestion/v1/constants'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import './Panels.scss'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'

export function PlatformPanel(): JSX.Element {
    const { setPlatform } = useActions(ingestionLogic)

    return (
        <div>
            <h1 className="ingestion-title">Welcome to PostHog</h1>
            <p>
                First things first, where do you want to send events from? You can always instrument more sources later.
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
                        onClick={() => setPlatform(platform)}
                    >
                        {platform}
                    </LemonButton>
                ))}
                <LemonButton
                    onClick={() => setPlatform(THIRD_PARTY)}
                    fullWidth
                    center
                    size="large"
                    className="mb-2"
                    type="primary"
                >
                    {THIRD_PARTY}
                </LemonButton>
                <LemonButton type="secondary" size="large" fullWidth center onClick={() => setPlatform(BOOKMARKLET)}>
                    {BOOKMARKLET}
                </LemonButton>
            </div>
        </div>
    )
}
