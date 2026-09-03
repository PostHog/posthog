import { useActions, useValues } from 'kea'

import { LemonBanner, LemonSkeleton } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { SceneExport } from 'scenes/sceneTypes'

import { FeaturePreviewSceneGate } from '~/layout/scenes/components/FeaturePreviewSceneGate'
import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { AccountDetailTabs } from '../../components/Accounts/AccountDetailTabs'
import { AccountLogo } from '../../components/Accounts/AccountLogo'
import { CustomerAnalyticsScene } from '../../CustomerAnalyticsScene'
import { customerAnalyticsFeaturePreviewGate } from '../../featurePreviewGate'
import type { AccountApi } from '../../generated/api.schemas'
import { AccountDetailActions } from './AccountDetailActions'
import { AccountSidebar } from './AccountSidebar'
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

function getAccountLogoDomain(account: AccountApi): string | null {
    return account.properties?.website_domain ?? account.properties?.email_domains?.[0] ?? null
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
                resourceType={{
                    type: 'cohort',
                    forceIcon: <AccountLogo domain={getAccountLogoDomain(account)} name={account.name} />,
                }}
                actions={<AccountDetailActions />}
            />
            <SceneDivider />
            <div className="@container/account-detail flex flex-1 min-h-0 overflow-y-auto @min-[60rem]:-mt-4 @min-[60rem]:-ml-4">
                <div className="flex min-h-full w-full flex-col gap-4 @min-[60rem]/account-detail:flex-row">
                    <AccountSidebar account={account} />
                    <main className="flex-1 min-w-0" data-attr="account-detail-tabs">
                        <AccountDetailTabs
                            accountId={account.id}
                            externalId={account.external_id ?? ''}
                            activeTab={activeTab}
                            onChange={setActiveTab}
                            embedded={false}
                        />
                    </main>
                </div>
            </div>
        </SceneContent>
    )
}
