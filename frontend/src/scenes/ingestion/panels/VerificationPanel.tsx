import './Panels.scss'

import { useActions, useValues } from 'kea'
import { useInterval } from 'lib/hooks/useInterval'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { teamLogic } from 'scenes/teamLogic'

import { CardContainer } from '../CardContainer'
import { IngestionInviteMembersButton } from '../IngestionInviteMembersButton'
import { ingestionLogic } from '../ingestionLogic'

export function VerificationPanel(): JSX.Element {
    const { loadCurrentTeam } = useActions(teamLogic)
    const { currentTeam } = useValues(teamLogic)
    const { next } = useActions(ingestionLogic)
    const { reportIngestionContinueWithoutVerifying } = useActions(eventUsageLogic)

    useInterval(() => {
        if (!currentTeam?.ingested_event) {
            loadCurrentTeam()
        }
    }, 2000)

    return !currentTeam?.ingested_event ? (
        <CardContainer>
            <div className="text-center">
                <div className="ingestion-listening-for-events">
                    <Spinner className="text-4xl" />
                    <h1 className="ingestion-title pt-4">Listening for events...</h1>
                    <p className="prompt-text">
                        Once you have integrated the snippet and sent an event, we will verify it was properly received
                        and continue.
                    </p>
                    <IngestionInviteMembersButton />
                    <LemonButton
                        fullWidth
                        center
                        type="tertiary"
                        onClick={() => {
                            next({ showSuperpowers: true })
                            reportIngestionContinueWithoutVerifying()
                        }}
                    >
                        or continue without verifying
                    </LemonButton>
                </div>
            </div>
        </CardContainer>
    ) : (
        <CardContainer nextProps={{ showSuperpowers: true }} showInviteTeamMembers={false}>
            <div className="text-center">
                <div>
                    <h1 className="ingestion-title">Successfully sent events!</h1>
                    <p className="prompt-text text-muted text-left">
                        You will now be able to explore PostHog and take advantage of all its features to understand
                        your users.
                    </p>
                </div>
            </div>
        </CardContainer>
    )
}
