import { useActions } from 'kea'
import { ingestionLogic } from 'scenes/ingestion/ingestionLogic'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import './Panels.scss'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { IconChevronRight } from 'lib/lemon-ui/icons'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { DemoProjectButton } from './PanelComponents'

export function TeamInvitedPanel(): JSX.Element {
    const { completeOnboarding } = useActions(ingestionLogic)
    const { reportIngestionContinueWithoutVerifying } = useActions(eventUsageLogic)

    return (
        <div>
            <h1 className="ingestion-title">Help is on the way!</h1>
            <p className="prompt-text">You can still explore PostHog while you wait for your team members to join.</p>
            <LemonDivider thick dashed className="my-6" />
            <div className="flex flex-col mb-6">
                <DemoProjectButton
                    text="Quickly try PostHog with some demo data."
                    subtext="Explore insights, create dashboards, try out cohorts, and more."
                />
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
