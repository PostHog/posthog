import { LemonInput, LemonSelect, LemonTable, LemonTag, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { normalizeColumnTitle } from 'lib/components/Table/utils'
import { capitalizeFirstLetter } from 'lib/utils'
import stringWithWBR from 'lib/utils/stringWithWBR'
import { urls } from 'scenes/urls'
import { FeatureFlagReleaseType } from '~/types'
import { relatedFeatureFlagsLogic, RelatedFeatureFlag } from './relatedFeatureFlagsLogic'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'

interface Props {
    distinctId: string
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

export function RelatedFeatureFlags({ distinctId, groups }: Props): JSX.Element {
    const { filteredMappedFlags, relatedFeatureFlagsLoading, searchTerm, filters } = useValues(
        relatedFeatureFlagsLogic({ distinctId, groups })
    )
    const { setSearchTerm, setFilters } = useActions(relatedFeatureFlagsLogic({ distinctId, groups }))

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
                            <LemonTag type={isExperiment ? 'completion' : 'default'} className="ml-2">
                                {isExperiment ? 'Experiment' : 'Feature flag'}
                            </LemonTag>
                        </Link>
                        {featureFlag.name && (
                            <LemonMarkdown className="row-description" lowKeyHeadings>
                                {featureFlag.name}
                            </LemonMarkdown>
                        )}
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
            width: 150,
            render: function Render(_, featureFlag: RelatedFeatureFlag) {
                return (
                    <div style={{ wordBreak: 'break-word' }}>
                        {featureFlag.active && featureFlag.value
                            ? capitalizeFirstLetter(featureFlag.value.toString())
                            : 'False'}
                    </div>
                )
            },
        },
        {
            title: 'Match evaluation',
            dataIndex: 'evaluation',
            width: 150,
            render: function Render(_, featureFlag: RelatedFeatureFlag) {
                const matchesSet = featureFlag.evaluation.reason === FeatureFlagMatchReason.ConditionMatch
                return (
                    <div>
                        {featureFlag.active ? <>{featureFlagMatchMapping[featureFlag.evaluation.reason]}</> : '--'}

                        {matchesSet && (
                            <span className="simple-tag ml-2" style={{ background: 'var(--primary-highlight)' }}>
                                Set {(featureFlag.evaluation.condition_index ?? 0) + 1}
                            </span>
                        )}
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
            <div className="flex justify-between mb-4">
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
                        value="all"
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
                        value="all"
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
                        value="all"
                        dropdownMaxContentWidth
                    />
                </div>
            </div>
            <LemonTable columns={columns} loading={relatedFeatureFlagsLoading} dataSource={filteredMappedFlags} />
        </>
    )
}
