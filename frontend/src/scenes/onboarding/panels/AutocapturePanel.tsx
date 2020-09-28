import { CardContainer } from 'scenes/onboarding/CardContainer'
import { Row } from 'antd'
import { JSSnippet } from 'lib/components/JSSnippet'
import React from 'react'
import { useActions, useValues } from 'kea'
import { onboardingLogic } from 'scenes/onboarding/onboardingLogic'

export function AutocapturePanel(): JSX.Element {
    const { index, totalSteps } = useValues(onboardingLogic)
    const { setPlatformType, setCustomEvent, setVerify } = useActions(onboardingLogic)
    return (
        <CardContainer
            index={index}
            totalSteps={totalSteps}
            nextButton={true}
            onSubmit={() => setVerify(true)}
            onBack={() => setPlatformType(null)}
        >
            <Row style={{ marginLeft: -5 }} justify="space-between" align="middle">
                <h2 style={{ color: 'black', marginLeft: 8 }}>{'Autocapture'}</h2>
                <b
                    style={{ marginLeft: 5, color: '#007bff', marginBottom: 10, marginRight: 0 }}
                    onClick={() => setCustomEvent(true)}
                    className="button-border clickable"
                >
                    I also want to capture custom events
                </b>
            </Row>
            <p className="prompt-text">
                Since you're running a web application, we suggest using our header snippet. This snippet will
                automatically capture page views, page leaves, and interactions with specific elements (
                {'<a>, <button>, <input>, <textarea>, <form>'}).
            </p>
            <p className="prompt-text">
                Just insert this snippet into your website where you configure {'<head> or <meta>'} tags.
            </p>
            <JSSnippet />
            <h2>Send an Event</h2>
            <p className="prompt-text">
                Once you've inserted the snippet, click on a button or form on your website to send an event!
            </p>
        </CardContainer>
    )
}
