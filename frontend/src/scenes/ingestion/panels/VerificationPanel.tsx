import React from 'react'
import { useActions, useValues } from 'kea'
import { useInterval } from 'lib/hooks/useInterval'
import { CardContainer } from 'scenes/ingestion/CardContainer'
import { ingestionLogic } from 'scenes/ingestion/ingestionLogic'
import { teamLogic } from 'scenes/teamLogic'
import { Spinner } from 'lib/components/Spinner/Spinner'
import { LemonButton } from 'lib/components/LemonButton'
import { PanelSupport } from './PanelComponents'
import './Panels.scss'
import { IconCheckCircleOutline } from 'lib/components/icons'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { EventBufferNotice } from 'scenes/events/EventBufferNotice'

export function VerificationPanel(): JSX.Element {
    const { loadCurrentTeam } = useActions(teamLogic)
    const { currentTeam } = useValues(teamLogic)
    const { setVerify, completeOnboarding } = useActions(ingestionLogic)
    const { index, onboardingSidebarEnabled } = useValues(ingestionLogic)
    const { reportIngestionContinueWithoutVerifying } = useActions(eventUsageLogic)

    useInterval(() => {
        if (!currentTeam?.ingested_event) {
            loadCurrentTeam()
        }
    }, 2000)

    return (
        <CardContainer index={index} onBack={() => setVerify(false)}>
            <div style={{ paddingLeft: 24, paddingRight: 24 }} className="text-center">
                {!currentTeam?.ingested_event ? (
                    <>
                        <div className="ingestion-listening-for-events">
                            <Spinner size="lg" />
                            <h1 className="ingestion-title pt">Listening for events...</h1>
                            <p className="prompt-text">
                                Once you have integrated the snippet and sent an event, we will verify it was properly
                                received and continue.
                            </p>
                            <EventBufferNotice style={{ marginTop: 0 }} />
                            <LemonButton
                                fullWidth
                                center
                                type="secondary"
                                onClick={() => {
                                    completeOnboarding()
                                    reportIngestionContinueWithoutVerifying()
                                }}
                            >
                                Continue without verifying
                            </LemonButton>
                        </div>
                        {!onboardingSidebarEnabled && <PanelSupport />}
                    </>
                ) : (
                    <>
                        <IconCheckCircleOutline style={{ color: 'var(--success)' }} />
                        <h1 className="ingestion-title">Successfully sent events!</h1>
                        <p className="prompt-text text-muted">
                            You will now be able to explore PostHog and take advantage of all its features to understand
                            your users.
                        </p>
                        <div className="mb">
                            <LemonButton
                                data-attr="wizard-complete-button"
                                type="primary"
                                onClick={() => completeOnboarding()}
                                fullWidth
                                center
                            >
                                Complete
                            </LemonButton>
                        </div>
                        {!onboardingSidebarEnabled && <PanelSupport />}
                    </>
                )}
            </div>
        </CardContainer>
    )
}
