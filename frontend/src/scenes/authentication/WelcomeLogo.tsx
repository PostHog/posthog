import React from 'react'
import cloudLogo from 'public/posthog-logo-cloud.svg'
import demoLogo from 'public/posthog-logo-demo.svg'
import defaultLogo from 'public/posthog-logo-default.svg'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { useValues } from 'kea'

export function WelcomeLogo({ view }: { view?: string }): JSX.Element {
    const UTM_TAGS = `utm_campaign=in-product&utm_tag=${view || 'welcome'}-header`
    const { preflight } = useValues(preflightLogic)

    return (
        <a href={`https://posthog.com?${UTM_TAGS}`}>
            <div className="header-logo">
                <img
                    src={preflight?.demo ? demoLogo : preflight?.cloud ? cloudLogo : defaultLogo}
                    alt={`PostHog${preflight?.cloud ? ' Cloud' : ''}`}
                />
            </div>
        </a>
    )
}
