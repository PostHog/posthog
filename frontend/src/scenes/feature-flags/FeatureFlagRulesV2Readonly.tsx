import { useValues } from 'kea'

import { LemonBanner, LemonTable, LemonTag } from '@posthog/lemon-ui'

import PropertyFiltersDisplay from 'lib/components/PropertyFilters/components/PropertyFiltersDisplay'
import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { capitalizeFirstLetter } from 'lib/utils/strings'

import { groupsModel } from '~/models/groupsModel'
import { FeatureFlagConfig, FeatureFlagRulesV2Config, FeatureFlagRulesV2Rule } from '~/types'

import { formatPercentage } from 'products/feature_flags/frontend/FractionalRolloutWarning'

import { featureFlagConfigFormat, featureFlagConfigFormatLabel } from './featureFlagConfigFormat'

const RULE_TYPE_LABELS: Record<FeatureFlagRulesV2Rule['rule_type'], string> = {
    targeted_release: 'Targeted release',
    percentage_rollout: 'Percentage rollout',
    experiment: 'Experiment',
}

export function FeatureFlagConfigReadonlyNotice({ filters }: { filters: FeatureFlagConfig }): JSX.Element {
    const label = featureFlagConfigFormatLabel(filters)
    return (
        <LemonBanner type="info">
            {featureFlagConfigFormat(filters) === 'v2' ? (
                <>
                    This flag is stored as <strong>{label}</strong> and is shown read-only here. You can enable, disable
                    and archive it; editing its rules is not available yet.
                </>
            ) : (
                <>
                    This flag is stored as <strong>{label}</strong>, which this page cannot display. You can disable and
                    archive it.
                </>
            )}
        </LemonBanner>
    )
}

function JsonValue({ value }: { value: unknown }): JSX.Element {
    return <code className="text-xs break-all">{JSON.stringify(value)}</code>
}

function RolloutCell({ rule }: { rule: FeatureFlagRulesV2Rule }): JSX.Element {
    if (rule.rule_type === 'targeted_release') {
        return <span>Everyone matching</span>
    }
    return (
        <div className="flex flex-col gap-1">
            <span className="tabular-nums">{formatPercentage(rule.rollout_percentage)}</span>
            <span className="text-xs text-muted">
                {rule.on_rollout_miss === 'continue' ? 'Miss: next rule' : 'Miss: default value'}
            </span>
        </div>
    )
}

function ValueCell({ rule }: { rule: FeatureFlagRulesV2Rule }): JSX.Element {
    if (rule.rule_type !== 'experiment') {
        return <JsonValue value={rule.value} />
    }
    return (
        <div className="flex flex-col gap-1">
            <div className="flex items-center gap-1">
                <span>Experiment #{rule.experiment_id}</span>
                {rule.paused && (
                    <LemonTag type="warning" size="small">
                        Paused
                    </LemonTag>
                )}
            </div>
            {rule.variants.map((variant) => (
                <div key={variant.key} className="flex items-center gap-2 text-xs">
                    <span className="font-mono">{variant.key}</span>
                    <span className="tabular-nums text-muted">{formatPercentage(variant.weight)}</span>
                    <JsonValue value={variant.value} />
                </div>
            ))}
            {rule.holdout && (
                <span className="text-xs text-muted">
                    Holdout #{rule.holdout.id} excludes {formatPercentage(rule.holdout.exclusion_percentage)}
                </span>
            )}
        </div>
    )
}

export function FeatureFlagRulesV2Readonly({ config }: { config: FeatureFlagRulesV2Config }): JSX.Element {
    const { aggregationLabel } = useValues(groupsModel)
    const subjects =
        config.aggregation_group_type_index != null
            ? aggregationLabel(config.aggregation_group_type_index).plural
            : 'users'

    const columns: LemonTableColumns<FeatureFlagRulesV2Rule> = [
        {
            title: '#',
            width: 0,
            render: (_, __, index) => <span className="tabular-nums">{index + 1}</span>,
        },
        {
            title: 'Type',
            width: 0,
            render: (_, rule) => (
                <LemonTag type="default" className="whitespace-nowrap">
                    {RULE_TYPE_LABELS[rule.rule_type]}
                </LemonTag>
            ),
        },
        {
            title: 'Description',
            render: (_, rule) => rule.description || <span className="text-muted">—</span>,
        },
        {
            title: 'Targeting',
            render: (_, rule) =>
                rule.targeting.properties.length > 0 ? (
                    <PropertyFiltersDisplay filters={rule.targeting.properties} compact />
                ) : (
                    <span className="text-muted">All {subjects}</span>
                ),
        },
        {
            title: 'Rollout',
            width: 0,
            render: (_, rule) => <RolloutCell rule={rule} />,
        },
        {
            title: 'Value',
            render: (_, rule) => <ValueCell rule={rule} />,
        },
    ]

    return (
        <div className="flex flex-col gap-4" data-attr="feature-flag-rules-v2-readonly">
            <FeatureFlagConfigReadonlyNotice filters={config} />
            <div className="flex flex-wrap gap-6 text-sm">
                <div className="flex flex-col gap-1">
                    <span className="font-semibold">Return type</span>
                    <LemonTag type="default">{capitalizeFirstLetter(config.return_type)}</LemonTag>
                </div>
                <div className="flex flex-col gap-1">
                    <span className="font-semibold">Default value</span>
                    <JsonValue value={config.default_value} />
                </div>
                <div className="flex flex-col gap-1">
                    <span className="font-semibold">Evaluated per</span>
                    <span>{capitalizeFirstLetter(subjects)}</span>
                </div>
            </div>
            <div className="flex flex-col gap-2">
                <span className="font-semibold">Rules</span>
                <p className="text-xs text-muted m-0">Rules are evaluated top to bottom; the first match decides.</p>
                <LemonTable
                    dataSource={config.rules}
                    columns={columns}
                    rowKey="id"
                    size="small"
                    emptyState="No rules: every evaluation returns the default value."
                />
            </div>
        </div>
    )
}
