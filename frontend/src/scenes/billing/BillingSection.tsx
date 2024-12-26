import './Billing.scss'
import './BillingSection.scss'

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
            push(urls.organizationBillingOverview())
        }
    }, [location.pathname])

    return (
        <div className="BillingSection flex">
            <div className="BillingSection__sections">
                <ul className="space-y-px">
                    <li>
                        <LemonButton
                            onClick={() => push(urls.organizationBillingOverview())}
                            status={activeSection === 'overview' ? 'primary' : 'default'}
                            size="small"
                            fullWidth
                        >
                            Overview
                        </LemonButton>
                    </li>
                    <li>
                        <LemonButton
                            onClick={() => push(urls.organizationBillingUsage())}
                            status={activeSection === 'usage' ? 'primary' : 'default'}
                            size="small"
                            fullWidth
                        >
                            Usage
                        </LemonButton>
                    </li>
                </ul>
            </div>
            <div className="flex-1 w-full space-y-2 min-w-0">
                {activeSection === 'overview' ? <BillingOverview /> : <BillingUsage />}
            </div>
        </div>
    )
}
