import { useActions, useValues } from 'kea'
import { userLogic } from 'scenes/userLogic'
import { useInterval } from 'lib/hooks/useInterval'
import { CardContainer } from 'scenes/onboarding/CardContainer'
import { Button, Row, Spin } from 'antd'
import React from 'react'

export function VerificationPanel({ reverse }: { reverse: () => void }): JSX.Element {
    const { loadUser, userUpdateRequest } = useActions(userLogic)
    const { user } = useValues(userLogic)

    useInterval(() => {
        !user?.has_events && loadUser()
    }, 3000)

    return (
        <CardContainer index={3} totalSteps={4} onBack={reverse}>
            {!user?.has_events ? (
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
                        onClick={() => userUpdateRequest({ team: { completed_snippet_onboarding: true } })}
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
                        onClick={() => userUpdateRequest({ team: { completed_snippet_onboarding: true } })}
                    >
                        Complete
                    </Button>
                </>
            )}
        </CardContainer>
    )
}
