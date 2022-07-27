import React from 'react'
import './BillingSubscribed.scss'
import { CloseCircleOutlined } from '@ant-design/icons'
import { useValues } from 'kea'
import { SceneExport } from 'scenes/sceneTypes'
import { billingLogic } from './billingLogic'
import { BillingSubscribedTheme } from './BillingSubscribed'
import { compactNumber } from 'lib/utils'
import { LemonButton } from '@posthog/lemon-ui'

export const scene: SceneExport = {
    component: BillingLocked,
}

export function BillingLocked(): JSX.Element | null {
    const { billing } = useValues(billingLogic)
    return billing ? (
        <BillingSubscribedTheme>
            <div className="title">
                <CloseCircleOutlined style={{ color: 'var(--danger)' }} className="title-icon" />
                <h2 className="subtitle">Please enter a credit card</h2>
            </div>
            <p>
                You've used <strong>{compactNumber(billing.current_usage)}</strong> events this month. To continue using
                PostHog, you'll need to enter a credit card. See{' '}
                <a href="https://posthog.com/pricing" target="_blank">
                    our website for pricing information.
                </a>
            </p>
            <div className="mt text-center">
                <LemonButton
                    className="cta-button"
                    type="primary"
                    size="large"
                    center={true}
                    href={billing.subscription_url}
                >
                    Continue to verify card
                </LemonButton>
            </div>
        </BillingSubscribedTheme>
    ) : null
}
