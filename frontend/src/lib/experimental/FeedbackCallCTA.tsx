import React from 'react'
import './NPSPrompt.scss' // Lazy, but this is an experimental feature so not worth optimizing
import { CloseOutlined } from '@ant-design/icons'
import { Button } from 'antd'
import { kea, useActions, useValues } from 'kea'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { feedbackCallLogicType } from './FeedbackCallCTAType'
import posthog from 'posthog-js'
import { successToast } from 'lib/utils'

const FEEDBACK_CALL_LOCALSTORAGE_KEY = 'call-cta-exp-2201'
const APPEAR_TIMEOUT = 15000

const COPY = [
    {
        title: 'Experimentation is launching!',
        description:
            'Experimentation can help you test which product changes optimize your metrics. Give us feedback on your needs!',
    },
    {
        title: 'Want to test product changes before shipping? 🧪',
        description:
            'Our new A/B testing feature is launching soon and will let you seamlessly run experiments on your product. Interested?',
    },
    {
        title: 'Introducing A/B testing 🚀',
        description:
            'We are launching our A/B testing suite soon! Share your feedback, help us shape this new feature.',
    },
]

const feedbackCallLogic = kea<feedbackCallLogicType>({
    path: ['lib', 'experimental', 'FeedbackCallCTA'],
    selectors: {
        featureFlagGroup: [
            () => [featureFlagLogic.selectors.featureFlags],
            (featureFlags): null | 'control' | 'variant-0' | 'variant-1' =>
                featureFlags[FEATURE_FLAGS.FEEDBACK_CALL_CTA] as null | 'control' | 'variant-0' | 'variant-1',
        ],
        copy: [
            (s) => [s.featureFlagGroup],
            (featureFlagGroup) =>
                featureFlagGroup === 'control'
                    ? COPY[0]
                    : featureFlagGroup === 'variant-0'
                    ? COPY[1]
                    : featureFlagGroup === 'variant-1'
                    ? COPY[2]
                    : null,
        ],
    },
    actions: {
        reportAndDismiss: (result: 'call' | 'more-info' | 'not-interested' | 'dismiss') => ({ result }),
        show: true,
        hide: true,
    },
    reducers: {
        hidden: [true, { show: () => false, hide: () => true }],
    },
    listeners: ({ actions }) => ({
        reportAndDismiss: ({ result }) => {
            posthog.capture('experimentation call prompt action', { result })
            localStorage.setItem(FEEDBACK_CALL_LOCALSTORAGE_KEY, 'true')
            actions.hide()
            if (result === 'more-info') {
                successToast(
                    "We'll be in touch soon!",
                    'We will send you more information on this feature to your email in the next few days.'
                )
            }
        },
    }),
    events: ({ actions, values, cache }) => ({
        afterMount: () => {
            if (
                values.featureFlagGroup?.startsWith('variant') &&
                !localStorage.getItem(FEEDBACK_CALL_LOCALSTORAGE_KEY)
            ) {
                cache.timeout = window.setTimeout(() => actions.show(), APPEAR_TIMEOUT)
            }
        },
        beforeUnmount: () => {
            window.clearTimeout(cache.timeout)
        },
    }),
})

export function FeedbackCallCTA(): JSX.Element {
    const { hidden, copy } = useValues(feedbackCallLogic)
    const { reportAndDismiss } = useActions(feedbackCallLogic)

    return (
        <div className={`nps-prompt${hidden ? ' hide' : ''}`}>
            <span className="nps-dismiss" onClick={() => reportAndDismiss('dismiss')}>
                <CloseOutlined />
            </span>
            {copy && (
                <div className="prompt-inner">
                    <div className="prompt-title">{copy.title}</div>
                    <div className="question">{copy.description}</div>
                    <div className="action-buttons" style={{ width: 240 }}>
                        <a
                            href="https://calendly.com/posthog-feedback"
                            target="_blank"
                            rel="noreferrer"
                            onClick={() => reportAndDismiss('call')}
                        >
                            <Button className="prompt-button">Schedule call with Eng Team</Button>
                        </a>
                        <Button className="prompt-button" onClick={() => reportAndDismiss('more-info')}>
                            Send me more info
                        </Button>
                        <Button className="prompt-button" onClick={() => reportAndDismiss('not-interested')}>
                            Not interested
                        </Button>
                    </div>
                </div>
            )}
        </div>
    )
}
