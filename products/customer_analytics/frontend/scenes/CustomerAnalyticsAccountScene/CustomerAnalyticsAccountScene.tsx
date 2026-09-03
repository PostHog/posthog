import { useActions, useValues } from 'kea'

import { LemonBanner, LemonSkeleton } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { FEATURE_FLAGS } from 'lib/constants'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { SceneExport } from 'scenes/sceneTypes'

import { FeaturePreviewSceneGate } from '~/layout/scenes/components/FeaturePreviewSceneGate'
import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { AccountDetailTabs } from '../../components/Accounts/AccountDetailTabs'
import { CustomerAnalyticsScene } from '../../CustomerAnalyticsScene'
import { customerAnalyticsFeaturePreviewGate } from '../../featurePreviewGate'
import { AccountDetailActions } from './AccountDetailActions'
import { AccountIdentityRail } from './AccountIdentityRail'
import {
    CustomerAnalyticsAccountSceneLogicProps,
    customerAnalyticsAccountSceneLogic,
} from './customerAnalyticsAccountSceneLogic'

export const scene: SceneExport<CustomerAnalyticsAccountSceneLogicProps> = {
    component: CustomerAnalyticsAccountScene,
    logic: customerAnalyticsAccountSceneLogic,
    productKey: ProductKey.CUSTOMER_ANALYTICS,
    paramsToProps: ({ params: { accountId } }) => ({ accountId: accountId ?? '' }),
}

export function CustomerAnalyticsAccountScene(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)

    if (!featureFlags[FEATURE_FLAGS.CUSTOMER_ANALYTICS_ACCOUNT_SCENE]) {
        return <CustomerAnalyticsScene />
    }

    if (!featureFlags[FEATURE_FLAGS.CUSTOMER_ANALYTICS_CSP]) {
        return <NotFound object="page" />
    }

    return (
        <FeaturePreviewSceneGate config={customerAnalyticsFeaturePreviewGate}>
            <CustomerAnalyticsAccountSceneContent />
        </FeaturePreviewSceneGate>
    )
}

function CustomerAnalyticsAccountSceneContent(): JSX.Element {
    const { account, accountLoadError, accountLoading, activeTab, isAccountMissing } = useValues(
        customerAnalyticsAccountSceneLogic
    )
    const { loadAccount, setActiveTab } = useActions(customerAnalyticsAccountSceneLogic)

    useOnMountEffect(loadAccount)

    if (isAccountMissing) {
        return <NotFound object="account" />
    }

    if (!account && accountLoadError) {
        return (
            <SceneContent className="h-full">
                <LemonBanner
                    type="error"
                    action={{ children: 'Try again', onClick: loadAccount, loading: accountLoading }}
                >
                    Couldn't load this account. Try again.
                </LemonBanner>
            </SceneContent>
        )
    }

    if (!account) {
        return (
            <SceneContent className="h-full">
                <div className="flex flex-1 min-h-0 gap-4">
                    <LemonSkeleton className="h-full w-56" />
                    <LemonSkeleton className="h-32 flex-1" />
                </div>
            </SceneContent>
        )
    }

    return (
        <SceneContent className="h-full min-h-0" data-attr="customer-analytics-account-scene">
            <SceneTitleSection
                name={account.name}
                resourceType={{ type: 'cohort' }}
                actions={<AccountDetailActions />}
            />
            <div className="@container/account-detail flex flex-1 min-h-0 overflow-y-auto">
                <div className="flex min-h-full w-full flex-col gap-4 @min-[56rem]/account-detail:flex-row">
                    <AccountIdentityRail account={account} />
                    <main className="flex-1 min-w-0" data-attr="account-detail-tabs">
                        <AccountDetailTabs
                            accountId={account.id}
                            externalId={account.external_id ?? ''}
                            activeTab={activeTab}
                            onChange={setActiveTab}
                        />
                    </main>
                </div>
            </div>
        </SceneContent>
    )
}
