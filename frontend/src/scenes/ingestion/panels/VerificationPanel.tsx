import React from 'react'
import { useActions, useValues } from 'kea'
import { userLogic } from 'scenes/userLogic'
import { useInterval } from 'lib/hooks/useInterval'
import { CardContainer } from 'scenes/ingestion/CardContainer'
import { Button, Row, Spin } from 'antd'
import { ingestionLogic } from 'scenes/ingestion/ingestionLogic'

export function VerificationPanel(): JSX.Element {
    const { loadUser } = useActions(userLogic)
    const { user } = useValues(userLogic)
    const { setVerify, completeOnboarding } = useActions(ingestionLogic)
    const { index, totalSteps } = useValues(ingestionLogic)

    useInterval(() => {
        !user?.team?.ingested_event && loadUser()
    }, 3000)

    return (
        <CardContainer index={index} totalSteps={totalSteps} onBack={() => setVerify(false)}>
            {!user?.team?.ingested_event ? (
                <>
                    <Row align="middle">
                        <Spin />
                        <h2 className="ml-3">Listening for events!</h2>
                    </Row>
                    <p className="prompt-text">
                        {' '}
                        Once you have integrated the snippet and sent an event, we will verify it sent properly and
                        continue
                    </p>
                    <b
                        data-attr="wizard-complete-button"
                        style={{ float: 'right' }}
                        className="button-border clickable"
                        onClick={completeOnboarding}
                    >
                        Continue without verifying
                    </b>
                </>
            ) : (
                <>
                    <h2>Successfully sent events!</h2>
                    <p className="prompt-text">
                        You will now be able to explore PostHog and take advantage of all its features to understand
                        your users.
                    </p>
                    <Button
                        data-attr="wizard-complete-button"
                        type="primary"
                        style={{ float: 'right' }}
                        onClick={completeOnboarding}
                    >
                        Complete
                    </Button>
                </>
            )}
        </CardContainer>
    )
}
