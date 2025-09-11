import { useValues } from 'kea'
import { router } from 'kea-router'

import { LemonButton, LemonTable, LemonTag } from '@posthog/lemon-ui'

import { PageHeader } from 'lib/components/PageHeader'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { EarlyAccessFeatureType, ProductKey } from '~/types'

import { earlyAccessFeaturesLogic } from './earlyAccessFeaturesLogic'

export const scene: SceneExport = {
    component: EarlyAccessFeatures,
    logic: earlyAccessFeaturesLogic,
    settingSectionId: 'environment-feature-flags',
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
    const shouldShowEmptyState = earlyAccessFeatures.length == 0 && !earlyAccessFeaturesLoading

    return (
        <SceneContent forceNewSpacing>
            <SceneTitleSection
                name="Early access features"
                description="Allow your users to individually enable or disable features that are in public beta."
                resourceType={{
                    type: 'early_access_feature',
                }}
            />
            <SceneDivider />
            <PageHeader
                buttons={
                    <LemonButton type="primary" to={urls.earlyAccessFeature('new')}>
                        New feature
                    </LemonButton>
                }
            />
            <ProductIntroduction
                productName="Early access features"
                productKey={ProductKey.EARLY_ACCESS_FEATURES}
                thingName="feature"
                description="Allow your users to individually enable or disable features that are in public beta."
                isEmpty={shouldShowEmptyState}
                docsURL="https://posthog.com/docs/feature-flags/early-access-feature-management"
                action={() => router.actions.push(urls.earlyAccessFeature('new'))}
                className="my-0"
            />
            {!shouldShowEmptyState && (
                <LemonTable
                    loading={earlyAccessFeaturesLoading}
                    columns={[
                        {
                            title: 'Name',
                            key: 'name',
                            render(_, feature) {
                                return (
                                    <LemonTableLink
                                        title={feature.name}
                                        description={feature.description}
                                        to={urls.earlyAccessFeature(feature.id)}
                                    />
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
        </SceneContent>
    )
}
