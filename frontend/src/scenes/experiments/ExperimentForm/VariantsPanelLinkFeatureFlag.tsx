import { useState } from 'react'
import { P, match } from 'ts-pattern'

import { IconToggle } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { Link } from 'lib/lemon-ui/Link'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { urls } from 'scenes/urls'

import type { FeatureFlagType } from '~/types'

interface VariantsPanelLinkFeatureFlagProps {
    linkedFeatureFlag: FeatureFlagType | null
    setShowFeatureFlagSelector: () => void
    disabled?: boolean
}

const getTargetingSummary = (flag: FeatureFlagType): string[] => {
    return match(flag)
        .with({ is_simple_flag: true, rollout_percentage: P.not(P.nullish) }, (f) => [
            `${f.rollout_percentage}% of all users`,
        ])
        .with({ filters: { groups: P.when((g) => !g || g.length === 0) } }, () => ['All users'])
        .otherwise((f) =>
            f.filters.groups.map((group) => {
                const rollout = group.rollout_percentage != null ? `${group.rollout_percentage}% of ` : ''
                const users = group.properties?.length
                    ? `users matching ${group.properties.length} ${group.properties.length === 1 ? 'condition' : 'conditions'}`
                    : 'all users'
                const variant = group.variant ? ` → variant "${group.variant}"` : ''

                return `${rollout}${users}${variant}`
            })
        )
}

const TargetingSummary = ({ flag }: { flag: FeatureFlagType }): JSX.Element => {
    const [expanded, setExpanded] = useState(false)
    const conditions = getTargetingSummary(flag)
    const hasMultipleConditions = conditions.length > 2

    const displayConditions = expanded ? conditions : conditions.slice(0, 2)

    return (
        <div className="space-y-2">
            <div className="text-xs uppercase tracking-wide font-semibold text-muted">Targeting</div>
            <ul className="list-disc pl-4 text-sm space-y-1">
                {displayConditions.map((condition, index) => (
                    <li key={index}>{condition}</li>
                ))}
            </ul>
            {hasMultipleConditions && !expanded && (
                <button
                    onClick={() => setExpanded(true)}
                    className="text-sm text-link hover:underline cursor-pointer pl-4"
                >
                    +{conditions.length - 2} more {conditions.length - 2 === 1 ? 'condition' : 'conditions'}
                </button>
            )}
            {expanded && hasMultipleConditions && (
                <button
                    onClick={() => setExpanded(false)}
                    className="text-sm text-link hover:underline cursor-pointer pl-4"
                >
                    Show less
                </button>
            )}
        </div>
    )
}

export const VariantsPanelLinkFeatureFlag = ({
    linkedFeatureFlag,
    setShowFeatureFlagSelector,
    disabled = false,
}: VariantsPanelLinkFeatureFlagProps): JSX.Element => {
    if (!linkedFeatureFlag) {
        if (disabled) {
            return (
                <div className="text-danger text-sm">
                    You cannot change the feature flag when editing an experiment.
                </div>
            )
        }
        return (
            <div>
                <label className="text-sm font-semibold">Selected Feature Flag</label>
                <div className="mt-2 p-8 border border-dashed rounded-lg bg-bg-light flex flex-col items-center gap-3">
                    <div className="flex items-center gap-2">
                        <IconToggle className="text-muted text-2xl" />
                        <div className="text-base font-semibold">No feature flag selected</div>
                    </div>
                    <div className="text-sm text-muted-alt text-center">
                        Select an existing multivariate feature flag to use with this experiment
                    </div>
                    <LemonButton type="primary" size="small" onClick={setShowFeatureFlagSelector}>
                        Select Feature Flag
                    </LemonButton>
                </div>
            </div>
        )
    }

    const variants = linkedFeatureFlag.filters?.multivariate?.variants || []

    return (
        <div>
            <label className="text-sm font-semibold">Linked Feature Flag</label>
            <div className="mt-2 border rounded-lg bg-bg-light p-4 space-y-2">
                {/* Header: Flag key + link + change button */}
                <div className="flex flex-row gap-4">
                    <div className="flex items-center gap-2 min-w-0 flex-1">
                        <IconToggle className="text-lg flex-shrink-0" />
                        <div className="font-semibold text-base truncate">{linkedFeatureFlag.key}</div>
                        <Link
                            to={urls.featureFlag(linkedFeatureFlag.id as number)}
                            target="_blank"
                            className="flex items-center hover:text-link flex-shrink-0"
                            title="View feature flag"
                        >
                            <IconOpenInNew />
                        </Link>
                    </div>
                    {/* Only show Change button when not read-only */}

                    <LemonButton
                        type="secondary"
                        size="small"
                        onClick={setShowFeatureFlagSelector}
                        disabledReason={
                            disabled ? 'You cannot change the feature flag when editing an experiment.' : undefined
                        }
                    >
                        Change
                    </LemonButton>
                </div>

                {/* Status */}
                <div className="flex items-center gap-2">
                    <div
                        className={`w-2 h-2 rounded-full ${linkedFeatureFlag.active ? 'bg-success' : 'bg-muted'}`}
                        title={linkedFeatureFlag.active ? 'Active' : 'Inactive'}
                    />
                    <span className="text-sm font-medium">{linkedFeatureFlag.active ? 'Active' : 'Inactive'}</span>
                </div>

                {/* Description */}
                {linkedFeatureFlag.name && <div className="text-sm text-muted-alt">{linkedFeatureFlag.name}</div>}

                {/* Variants */}
                <div className="space-y-2">
                    <div className="text-xs uppercase tracking-wide font-semibold text-muted">Variants</div>
                    <div className="flex flex-wrap gap-1.5">
                        {variants.map(({ key }) => (
                            <LemonTag key={key} type={key === 'control' ? 'primary' : 'default'}>
                                {key}
                            </LemonTag>
                        ))}
                    </div>
                </div>

                {/* Targeting */}
                <TargetingSummary flag={linkedFeatureFlag} />
            </div>
        </div>
    )
}
