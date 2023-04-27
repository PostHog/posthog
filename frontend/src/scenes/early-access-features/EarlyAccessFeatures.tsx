import { LemonButton, LemonDivider, LemonTable, LemonTag, Link } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { FeatureType } from '~/types'
import { earlyAccessFeaturesLogic } from './earlyAccessFeaturesLogic'

export const scene: SceneExport = {
    component: EarlyAccessFeatures,
    logic: earlyAccessFeaturesLogic,
}

const STAGES_IN_ORDER: Record<FeatureType['stage'], number> = {
    concept: 0,
    alpha: 1,
    beta: 2,
    'general-availability': 3,
}

export function EarlyAccessFeatures(): JSX.Element {
    const { features, featuresLoading } = useValues(earlyAccessFeaturesLogic)

    return (
        <>
            <PageHeader
                title="Early Access Management"
                caption="Release features in a controlled way. Track adoption in stages."
                buttons={
                    <LemonButton type="primary" to={urls.earlyAccessFeature('new')}>
                        New release
                    </LemonButton>
                }
                delimited
            />
            <LemonTable
                loading={featuresLoading}
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
                    {
                        width: 0,
                        render(_, feature) {
                            return (
                                <More
                                    overlay={
                                        <>
                                            <LemonButton
                                                status="stealth"
                                                to={urls.earlyAccessFeature(feature.id)}
                                                fullWidth
                                            >
                                                View
                                            </LemonButton>
                                            <LemonDivider />
                                            <LemonButton
                                                status="danger"
                                                onClick={() => {
                                                    // TODO: Allow archival
                                                }}
                                                fullWidth
                                            >
                                                {/* Using "Archive" as "Deleting" a feature is very close to implying
                                    that it'll be deleted from code */}
                                                Archive feature
                                            </LemonButton>
                                        </>
                                    }
                                />
                            )
                        },
                    },
                ]}
                dataSource={features}
            />
        </>
    )
}
