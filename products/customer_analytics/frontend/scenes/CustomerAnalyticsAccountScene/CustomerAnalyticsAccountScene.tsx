import { useActions, useValues } from 'kea'

import { LemonBanner, LemonCard, LemonSkeleton } from '@posthog/lemon-ui'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
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
        <SceneContent>
            <SceneTitleSection name={account.name} resourceType={{ type: 'cohort' }} />
            <LemonCard hoverEffect={false} className="flex flex-col gap-1 max-w-xl">
                <span className="text-xs text-secondary">External ID</span>
                {account.external_id ? (
                    <CopyToClipboardInline explicitValue={account.external_id} description="external ID">
                        {account.external_id}
                    </CopyToClipboardInline>
                ) : (
                    <span className="text-secondary">Not set</span>
                )}
            </LemonCard>
        </SceneContent>
    )
}
