import './Billing.scss'

import { LemonButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect } from 'react'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { billingLogic } from './billingLogic'
import { BillingOverview } from './BillingOverview'
import { BillingUsage } from './BillingUsage'

export const scene: SceneExport = {
    component: BillingSection,
    logic: billingLogic,
}

export function BillingSection(): JSX.Element {
    const { location } = useValues(router)
    const { push } = useActions(router)

    const activeSection = location.pathname.endsWith('/usage') ? 'usage' : 'overview'

    useEffect(() => {
        if (location.pathname === '/organization/billing') {
            push(urls.organizationBillingSection('overview'))
        }
    }, [location.pathname])

    return (
        <div className="flex gap-8 items-start mt-0">
            <div className="sticky top-16 flex-shrink-0 w-1/5 min-w-56 max-w-80 [.SidePanel3000_&]:top-0">
                <ul className="deprecated-space-y-px">
                    <li>
                        <LemonButton
                            onClick={() => push(urls.organizationBillingSection('overview'))}
                            active={activeSection === 'overview'}
                            size="small"
                            fullWidth
                        >
                            Overview
                        </LemonButton>
                    </li>
                    <li>
                        <LemonButton
                            onClick={() => push(urls.organizationBillingSection('usage'))}
                            active={activeSection === 'usage'}
                            size="small"
                            fullWidth
                        >
                            Usage
                        </LemonButton>
                    </li>
                </ul>
            </div>
            <div className="flex-1 w-full deprecated-space-y-2 min-w-0">
                {activeSection === 'overview' ? <BillingOverview /> : <BillingUsage />}
            </div>
        </div>
    )
}
