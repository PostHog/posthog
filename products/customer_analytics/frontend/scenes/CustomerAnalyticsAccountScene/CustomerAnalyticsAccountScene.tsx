import { BindLogic, useActions, useValues } from 'kea'

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

import { CustomerAnalyticsScene } from '../../CustomerAnalyticsScene'
import { customerAnalyticsFeaturePreviewGate } from '../../featurePreviewGate'
import { AccountDetailCanvas } from './canvas/AccountDetailCanvas'
import {
    CustomerAnalyticsAccountSceneLogicProps,
    customerAnalyticsAccountSceneLogic,
} from './customerAnalyticsAccountSceneLogic'
import { AccountIdentityRail } from './rail/AccountIdentityRail'

export const scene: SceneExport<CustomerAnalyticsAccountSceneLogicProps> = {
    component: CustomerAnalyticsAccountScene,
    logic: customerAnalyticsAccountSceneLogic,
    productKey: ProductKey.CUSTOMER_ANALYTICS,
    paramsToProps: ({ params: { accountId } }) => ({ accountId: accountId ?? '' }),
}

export function CustomerAnalyticsAccountScene({ accountId }: CustomerAnalyticsAccountSceneLogicProps): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)

    if (!featureFlags[FEATURE_FLAGS.CUSTOMER_ANALYTICS_ACCOUNT_SCENE]) {
        return <CustomerAnalyticsScene />
    }

    if (!featureFlags[FEATURE_FLAGS.CUSTOMER_ANALYTICS_CSP]) {
        return <NotFound object="page" />
    }

    return (
        <FeaturePreviewSceneGate config={customerAnalyticsFeaturePreviewGate}>
            <BindLogic logic={customerAnalyticsAccountSceneLogic} props={{ accountId }}>
                <CustomerAnalyticsAccountSceneContent />
            </BindLogic>
        </FeaturePreviewSceneGate>
    )
}

function CustomerAnalyticsAccountSceneContent(): JSX.Element {
    const { account, accountLoadError, accountLoading, isAccountMissing } = useValues(
        customerAnalyticsAccountSceneLogic
    )
    const { loadAccount } = useActions(customerAnalyticsAccountSceneLogic)

    useOnMountEffect(loadAccount)

    if (isAccountMissing) {
        return <NotFound object="account" />
    }

    if (!account && accountLoadError) {
        return (
            <SceneContent>
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
            <SceneContent>
                <div className="flex flex-col gap-3 max-w-xl">
                    <LemonSkeleton className="h-6 w-56" />
                    <LemonSkeleton className="h-24 w-full" />
                </div>
            </SceneContent>
        )
    }

    return (
        <SceneContent className="h-full" data-attr="customer-analytics-account-scene">
            <SceneTitleSection name={account.name} resourceType={{ type: 'cohort' }} />
            <div className="flex flex-1 min-h-0 gap-4 overflow-hidden">
                <AccountIdentityRail account={account} />
                <AccountDetailCanvas account={account} />
            </div>
        </SceneContent>
    )
}
