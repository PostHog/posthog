import { LemonButton, LemonTable, LemonTag, Link } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { EarlyAccessFeatureType, ProductKey } from '~/types'
import { earlyAccessFeaturesLogic } from './earlyAccessFeaturesLogic'
import { userLogic } from 'scenes/userLogic'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { router } from 'kea-router'

export const scene: SceneExport = {
    component: EarlyAccessFeatures,
    logic: earlyAccessFeaturesLogic,
}

const STAGES_IN_ORDER: Record<EarlyAccessFeatureType['stage'], number> = {
    draft: 0,
    concept: 1,
    alpha: 2,
    beta: 3,
    'general-availability': 4,
    archived: 5,
}

export function EarlyAccessFeatures(): JSX.Element {
    const { earlyAccessFeatures, earlyAccessFeaturesLoading } = useValues(earlyAccessFeaturesLogic)
    const { user } = useValues(userLogic)

    const shouldShowEmptyState = earlyAccessFeatures.length == 0 && !earlyAccessFeaturesLoading
    const shouldShowProductIntroduction = !user?.has_seen_product_intro_for?.[ProductKey.EARLY_ACCESS_FEATURES]

    const showIntro = shouldShowProductIntroduction || shouldShowEmptyState
    return (
        <>
            <PageHeader
                title={
                    <div className="flex items-center gap-2">
                        Early Access Management
                        <LemonTag type="warning" className="uppercase">
                            Beta
                        </LemonTag>
                    </div>
                }
                caption={
                    !showIntro && (
                        <>
                            Allow your users to enable or disable features that are in public beta. Check out our{' '}
                            <Link
                                data-attr="early-access-management-help"
                                to="https://posthog.com/docs/feature-flags/early-access-feature-management?utm_medium=in-product&utm_campaign=learn-more"
                                target="_blank"
                            >
                                {' '}
                                documentation
                            </Link>{' '}
                            to learn more.
                        </>
                    )
                }
                buttons={
                    <LemonButton type="primary" to={urls.earlyAccessFeature('new')}>
                        Create feature
                    </LemonButton>
                }
                delimited
            />
            {showIntro && (
                <ProductIntroduction
                    productName="Early access features"
                    productKey={ProductKey.EARLY_ACCESS_FEATURES}
                    thingName="feature"
                    description="Allow your users to individually enable or disable features that are in public beta."
                    isEmpty={shouldShowEmptyState}
                    docsURL="https://posthog.com/docs/feature-flags/early-access-feature-management"
                    action={() => router.actions.push(urls.earlyAccessFeature('new'))}
                />
            )}
            {!shouldShowEmptyState && (
                <LemonTable
                    loading={earlyAccessFeaturesLoading}
                    columns={[
                        {
                            title: 'Name',
                            key: 'name',
                            render(_, feature) {
                                return (
                                    <>
                                        <Link to={urls.earlyAccessFeature(feature.id)}>
                                            <div className="row-name">{feature.name}</div>
                                        </Link>
                                        {feature.description && (
                                            <div className="row-description">{feature.description}</div>
                                        )}
                                    </>
                                )
                            },
                            sorter: (a, b) => a.name.localeCompare(b.name),
                        },
                        {
                            title: 'Stage',
                            dataIndex: 'stage',
                            render(_, { stage }) {
                                return (
                                    <LemonTag
                                        type={
                                            stage === 'beta'
                                                ? 'warning'
                                                : stage === 'general-availability'
                                                ? 'success'
                                                : 'default'
                                        }
                                        className="uppercase cursor-default"
                                    >
                                        {stage}
                                    </LemonTag>
                                )
                            },
                            sorter: (a, b) => STAGES_IN_ORDER[a.stage] - STAGES_IN_ORDER[b.stage],
                        },
                    ]}
                    dataSource={earlyAccessFeatures}
                />
            )}
        </>
    )
}
