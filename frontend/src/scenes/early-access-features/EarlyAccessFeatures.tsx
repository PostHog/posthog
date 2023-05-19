import { LemonButton, LemonTable, LemonTag, Link } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { EarlyAccsesFeatureType } from '~/types'
import { earlyAccessFeaturesLogic } from './earlyAccessFeaturesLogic'

export const scene: SceneExport = {
    component: EarlyAccessFeatures,
    logic: earlyAccessFeaturesLogic,
}

const STAGES_IN_ORDER: Record<EarlyAccsesFeatureType['stage'], number> = {
    concept: 0,
    alpha: 1,
    beta: 2,
    'general-availability': 3,
}

export function EarlyAccessFeatures(): JSX.Element {
    const { earlyAccessFeatures, earlyAccessFeaturesLoading } = useValues(earlyAccessFeaturesLogic)

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
                }
                buttons={
                    <LemonButton type="primary" to={urls.earlyAccessFeature('new')}>
                        New public beta
                    </LemonButton>
                }
                delimited
            />
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
        </>
    )
}
