import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { NotFound } from 'lib/components/NotFound'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { FEATURE_FLAGS } from 'lib/constants'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { SceneExport } from 'scenes/sceneTypes'

import { FeaturePreviewSceneGate } from '~/layout/scenes/components/FeaturePreviewSceneGate'
import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { AccountDetailTabs } from '../../components/Accounts/AccountDetailTabs'
import { AccountLogo } from '../../components/Accounts/AccountLogo'
import { CustomerAnalyticsScene } from '../../CustomerAnalyticsScene'
import { customerAnalyticsFeaturePreviewGate } from '../../featurePreviewGate'
import type { AccountApi } from '../../generated/api.schemas'
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

function openWorkInProgressDialog(title: string): void {
    LemonDialog.open({
        title,
        content: 'This feature is a work in progress.',
    })
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
            <SceneTitleSection name={account.name} resourceType={{ type: 'cohort' }} />
            <div className="@container/account-detail flex flex-1 min-h-0 overflow-y-auto">
                <div className="flex min-h-full w-full flex-col gap-4 @min-[56rem]/account-detail:flex-row">
                    <aside
                        className="w-full shrink-0 rounded border p-4 flex flex-col gap-4 @min-[56rem]/account-detail:w-56"
                        data-attr="account-identity-rail"
                    >
                        <div className="flex items-start gap-2 min-w-0">
                            <AccountLogo domain={getAccountLogoDomain(account)} name={account.name} />
                            <div className="flex flex-col min-w-0 gap-1">
                                <h2 className="text-base font-semibold mb-0 break-words">{account.name}</h2>
                                {account.external_id ? (
                                    <CopyToClipboardInline
                                        explicitValue={account.external_id}
                                        description="external ID"
                                        className="text-xs text-muted break-all"
                                    >
                                        {account.external_id}
                                    </CopyToClipboardInline>
                                ) : (
                                    <span className="text-xs text-muted">External ID not set</span>
                                )}
                            </div>
                        </div>
                        <div className="flex flex-col gap-1" data-attr="account-rail-tags">
                            <span className="text-xs text-secondary">Tags</span>
                            <ObjectTags tags={account.tags ?? []} staticOnly wrap />
                        </div>
                    </aside>
                    <main className="flex-1 min-w-0" data-attr="account-detail-tabs">
                        <AccountDetailTabs
                            accountId={account.id}
                            externalId={account.external_id ?? ''}
                            activeTab={activeTab}
                            onChange={setActiveTab}
                            rightSlot={
                                <>
                                    <LemonButton
                                        type="secondary"
                                        size="small"
                                        data-attr="account-detail-configure-tabs"
                                        onClick={() => openWorkInProgressDialog('Configure tabs')}
                                    >
                                        Configure tabs
                                    </LemonButton>
                                    <LemonButton
                                        type="primary"
                                        size="small"
                                        data-attr="account-detail-add-view"
                                        onClick={() => openWorkInProgressDialog('Add view')}
                                    >
                                        Add view
                                    </LemonButton>
                                </>
                            }
                        />
                    </main>
                </div>
            </div>
        </SceneContent>
    )
}
