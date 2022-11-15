import { useActions } from 'kea'
import { ingestionLogicV2 } from 'scenes/ingestion/v2/ingestionLogic'
import { LemonButton } from 'lib/components/LemonButton'
import './Panels.scss'
import { LemonDivider } from 'lib/components/LemonDivider'
import { IconChevronRight } from 'lib/components/icons'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { BOOKMARKLET } from '../constants'

export function TeamInvitedPanel(): JSX.Element {
    const { completeOnboarding, setTechnical, setPlatform } = useActions(ingestionLogicV2)
    const { reportIngestionContinueWithoutVerifying } = useActions(eventUsageLogic)

    return (
        <div>
            <h1 className="ingestion-title">Help is on the way!</h1>
            <p className="prompt-text">
                You can still explore all PostHog has to offer while you wait for your team members to join.
            </p>
            <LemonDivider thick dashed className="my-6" />
            <div className="flex flex-col mb-6">
                <LemonButton
                    onClick={() => {
                        setTechnical(false)
                        setPlatform(BOOKMARKLET)
                    }}
                    fullWidth
                    size="large"
                    className="mb-4"
                    type="primary"
                    sideIcon={<IconChevronRight />}
                >
                    <div className="mt-4 mb-0">
                        <p className="mb-2">Quickly try PostHog with our Bookmarklet.</p>
                        <p className="font-normal text-xs">
                            Create a few events and experience all PostHog has to offer without any of the setup.
                        </p>
                    </div>
                </LemonButton>
                <LemonButton
                    onClick={() => {
                        completeOnboarding()
                        reportIngestionContinueWithoutVerifying()
                    }}
                    fullWidth
                    size="large"
                    className="mb-4"
                    type="secondary"
                    sideIcon={<IconChevronRight />}
                >
                    <div className="mt-4 mb-0">
                        <p className="mb-2">Continue without any events.</p>
                        <p className="font-normal text-xs">
                            It might look a little empty in there, but we'll do our best.
                        </p>
                    </div>
                </LemonButton>
            </div>
        </div>
    )
}
