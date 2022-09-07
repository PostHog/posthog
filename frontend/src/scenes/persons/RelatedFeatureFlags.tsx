import { LemonTable, LemonTag, Link } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { LemonTableColumns } from 'lib/components/LemonTable'
import { normalizeColumnTitle } from 'lib/components/Table/utils'
import { capitalizeFirstLetter } from 'lib/utils'
import stringWithWBR from 'lib/utils/stringWithWBR'
import React from 'react'
import { urls } from 'scenes/urls'
import { FeatureFlagReleaseType } from '~/types'
import { relatedFeatureFlagsLogic, RelatedFeatureFlag } from './relatedFeatureFlagsLogic'

interface Props {
    distinctId: string
}

enum FeatureFlagMatchReason {
    ConditionMatch = 'condition_match',
    NoConditionMatch = 'no_condition_match',
    OutOfRolloutBound = 'out_of_rollout_bound',
    NoGroupType = 'no_group_type',
    Disabled = 'disabled',
}

const featureFlagMatchMapping = {
    [FeatureFlagMatchReason.ConditionMatch]: 'Matches',
    [FeatureFlagMatchReason.NoConditionMatch]: "Doesn't match any conditions",
    [FeatureFlagMatchReason.OutOfRolloutBound]: 'Out of rollout bound',
    [FeatureFlagMatchReason.NoGroupType]: 'Missing group type',
    [FeatureFlagMatchReason.Disabled]: 'Disabled',
}

export function RelatedFeatureFlags({ distinctId }: Props): JSX.Element {
    const { mappedRelatedFeatureFlags, relatedFeatureFlagsLoading } = useValues(
        relatedFeatureFlagsLogic({ distinctId })
    )

    const columns: LemonTableColumns<RelatedFeatureFlag> = [
        {
            title: normalizeColumnTitle('Key'),
            dataIndex: 'key',
            className: 'ph-no-capture',
            sticky: true,
            width: '40%',
            sorter: (a: RelatedFeatureFlag, b: RelatedFeatureFlag) => (a.key || '').localeCompare(b.key || ''),
            render: function Render(_, featureFlag: RelatedFeatureFlag) {
                const isExperiment = (featureFlag.experiment_set || []).length > 0
                return (
                    <>
                        <Link to={featureFlag.id ? urls.featureFlag(featureFlag.id) : undefined} className="row-name">
                            {stringWithWBR(featureFlag.key, 17)}
                            <LemonTag type={isExperiment ? 'purple' : 'default'} className="ml-2">
                                {isExperiment ? 'Experiment' : 'Feature flag'}
                            </LemonTag>
                        </Link>
                        {featureFlag.name && <span className="row-description">{featureFlag.name}</span>}
                    </>
                )
            },
        },
        {
            title: 'Type',
            width: 100,
            render: function Render(_, featureFlag: RelatedFeatureFlag) {
                return featureFlag.filters.multivariate
                    ? FeatureFlagReleaseType.Variants
                    : FeatureFlagReleaseType.ReleaseToggle
            },
        },
        {
            title: 'Value',
            dataIndex: 'value',
            width: 100,
            render: function Render(_, featureFlag: RelatedFeatureFlag) {
                return <div>{capitalizeFirstLetter(featureFlag.value.toString())}</div>
            },
        },
        {
            title: 'Match evaluation',
            dataIndex: 'evaluation',
            width: 150,
            render: function Render(_, featureFlag: RelatedFeatureFlag) {
                return <div>{featureFlagMatchMapping[featureFlag.evaluation.reason] || '--'}</div>
            },
        },
        {
            title: 'Status',
            dataIndex: 'active',
            sorter: (a: RelatedFeatureFlag, b: RelatedFeatureFlag) => Number(a.active) - Number(b.active),
            width: 100,
            render: function RenderActive(_, featureFlag: RelatedFeatureFlag) {
                return <span className="font-normal">{featureFlag.active ? 'Enabled' : 'Disabled'}</span>
            },
        },
    ]
    return (
        <>
            <LemonTable columns={columns} loading={relatedFeatureFlagsLoading} dataSource={mappedRelatedFeatureFlags} />
        </>
    )
}
