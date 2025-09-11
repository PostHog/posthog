import { useActions, useValues } from 'kea'

import { IconInfo } from '@posthog/icons'
import { LemonInput, LemonSelect, LemonSnack, LemonTable, LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import stringWithWBR from 'lib/utils/stringWithWBR'
import { urls } from 'scenes/urls'

import { FeatureFlagReleaseType } from '~/types'

import { RelatedFeatureFlag, relatedFeatureFlagsLogic } from './relatedFeatureFlagsLogic'

interface Props {
    distinctId: string | null
    groupTypeIndex?: number
    groups?: { [key: string]: string }
}

export enum FeatureFlagMatchReason {
    SuperConditionMatch = 'super_condition_value',
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
    [FeatureFlagMatchReason.SuperConditionMatch]: 'Matches early access condition',
    [FeatureFlagMatchReason.Disabled]: 'Disabled',
}

export function RelatedFeatureFlags({ distinctId, groupTypeIndex, groups }: Props): JSX.Element {
    const relatedFlagsLogic = relatedFeatureFlagsLogic({ distinctId, groupTypeIndex, groups })
    const { filteredMappedFlags, relatedFeatureFlagsLoading, searchTerm, filters, pagination } =
        useValues(relatedFlagsLogic)
    const { setSearchTerm, setFilters } = useActions(relatedFlagsLogic)

    const columns: LemonTableColumns<RelatedFeatureFlag> = [
        {
            title: 'Key',
            dataIndex: 'key',
            className: 'ph-no-capture',
            sticky: true,
            width: '40%',
            sorter: (a: RelatedFeatureFlag, b: RelatedFeatureFlag) => (a.key || '').localeCompare(b.key || ''),
            render: function Render(_, featureFlag: RelatedFeatureFlag) {
                const isExperiment = (featureFlag.experiment_set || []).length > 0
                return (
                    <LemonTableLink
                        to={featureFlag.id ? urls.featureFlag(featureFlag.id) : undefined}
                        title={
                            <>
                                {stringWithWBR(featureFlag.key, 17)}
                                <LemonTag type={isExperiment ? 'completion' : 'default'} className="ml-2">
                                    {isExperiment ? 'Experiment' : 'Feature flag'}
                                </LemonTag>
                            </>
                        }
                        description={featureFlag.name}
                    />
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
            width: 150,
            render: function Render(_, featureFlag: RelatedFeatureFlag) {
                return (
                    <div className="break-words">
                        {featureFlag.active && featureFlag.value ? featureFlag.value.toString() : 'false'}
                    </div>
                )
            },
        },
        {
            title: (
                <div className="inline-flex items-center deprecated-space-x-1">
                    <div>Match evaluation</div>
                    <Tooltip
                        title={
                            <div className="deprecated-space-y-2">
                                <div>
                                    This column simulates the feature flag evaluation based on the selected distinct ID,
                                    current properties, and groups associated with the user. If the actual flag value
                                    differs, it could be due to different inputs used during evaluation.
                                </div>
                                <div>
                                    If you are using local flag evaluation, you must ensure that you provide any person
                                    properties, groups, or group properties used to evaluate the release conditions of
                                    the flag. Read more in the{' '}
                                    <Link to="https://posthog.com/docs/feature-flags/local-evaluation#step-3-evaluate-your-feature-flag">
                                        documentation.
                                    </Link>
                                </div>
                            </div>
                        }
                        closeDelayMs={200}
                    >
                        <IconInfo className="text-secondary text-base ml-1" />
                    </Tooltip>
                </div>
            ),
            dataIndex: 'evaluation',
            width: 150,
            render: function Render(_, featureFlag: RelatedFeatureFlag) {
                const matchesSet = featureFlag.evaluation.reason === FeatureFlagMatchReason.ConditionMatch
                return (
                    <div>
                        {featureFlag.active ? <>{featureFlagMatchMapping[featureFlag.evaluation.reason]}</> : '--'}

                        {matchesSet && <LemonSnack>Set {(featureFlag.evaluation.condition_index ?? 0) + 1}</LemonSnack>}
                    </div>
                )
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

    const options = [
        { label: 'All types', value: 'all' },
        {
            label: FeatureFlagReleaseType.ReleaseToggle,
            value: FeatureFlagReleaseType.ReleaseToggle,
        },
        { label: FeatureFlagReleaseType.Variants, value: FeatureFlagReleaseType.Variants },
    ]

    return (
        <>
            <div className="flex justify-between mb-4 gap-2 flex-wrap">
                <LemonInput
                    type="search"
                    placeholder="Search for feature flags"
                    onChange={setSearchTerm}
                    value={searchTerm}
                />
                <div className="flex items-center gap-2">
                    <span>
                        <b>Type</b>
                    </span>
                    <LemonSelect
                        options={options}
                        onChange={(type) => {
                            if (type) {
                                if (type === 'all') {
                                    if (filters) {
                                        const { type, ...restFilters } = filters
                                        setFilters(restFilters, true)
                                    }
                                } else {
                                    setFilters({ type })
                                }
                            }
                        }}
                        value={filters.type || 'all'}
                        dropdownMaxContentWidth
                    />
                    <span className="ml-2">
                        <b>Match evaluation</b>
                    </span>
                    <LemonSelect
                        options={
                            [
                                { label: 'All', value: 'all' },
                                { label: 'Matched', value: FeatureFlagMatchReason.ConditionMatch },
                                { label: 'Not matched', value: 'not matched' },
                            ] as { label: string; value: string }[]
                        }
                        onChange={(reason) => {
                            if (reason) {
                                if (reason === 'all') {
                                    if (filters) {
                                        const { reason, ...restFilters } = filters
                                        setFilters(restFilters, true)
                                    }
                                } else {
                                    setFilters({ reason })
                                }
                            }
                        }}
                        value={filters.reason || 'all'}
                        dropdownMaxContentWidth
                    />
                    <span className="ml-2">
                        <b>Flag status</b>
                    </span>
                    <LemonSelect
                        onChange={(status) => {
                            if (status) {
                                if (status === 'all') {
                                    if (filters) {
                                        const { active, ...restFilters } = filters
                                        setFilters(restFilters, true)
                                    }
                                } else {
                                    setFilters({ active: status })
                                }
                            }
                        }}
                        options={
                            [
                                { label: 'All', value: 'all' },
                                { label: 'Enabled', value: 'true' },
                                { label: 'Disabled', value: 'false' },
                            ] as { label: string; value: string }[]
                        }
                        value={filters.active || 'all'}
                        dropdownMaxContentWidth
                    />
                </div>
            </div>
            <LemonTable
                columns={columns}
                loading={relatedFeatureFlagsLoading}
                dataSource={filteredMappedFlags}
                pagination={pagination}
            />
        </>
    )
}
