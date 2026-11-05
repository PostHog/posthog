import { useValues } from 'kea'

import { Spinner } from '@posthog/lemon-ui'

import { DefinitionPopoverCard } from 'lib/components/DefinitionPopover/DefinitionPopoverCard'
import { DefinitionPopoverGrid } from 'lib/components/DefinitionPopover/DefinitionPopoverGrid'
import { pluralize } from 'lib/utils/strings'

import { featureFlagSummaryLogic } from 'products/feature_flags/frontend/featureFlagSummaryLogic'

export function FeatureFlagPopoverInfo({ flagKey }: { flagKey: string }): JSX.Element {
    const { summary, flagLoading, flagLoadFailed } = useValues(featureFlagSummaryLogic({ flagKey }))

    if (flagLoading) {
        return <Spinner />
    }
    if (flagLoadFailed) {
        return <span className="text-secondary">Could not load this flag. Try again in a moment.</span>
    }
    if (!summary) {
        return <span className="text-secondary">No flag with this key in this project</span>
    }

    return (
        <DefinitionPopoverGrid cols={1}>
            <DefinitionPopoverCard
                title="Status"
                value={summary.archived ? 'Archived' : summary.active ? 'Enabled' : 'Disabled'}
            />
            {summary.conditionCount !== null && (
                <DefinitionPopoverCard
                    title="Release conditions"
                    value={pluralize(summary.conditionCount, 'condition', 'conditions')}
                />
            )}
            {summary.variants && (
                <DefinitionPopoverCard
                    title="Variants"
                    value={
                        summary.variants.length > 0
                            ? summary.variants
                                  .map((variant) => `${variant.key} (${variant.rollout_percentage}%)`)
                                  .join(', ')
                            : 'None (true or false)'
                    }
                />
            )}
        </DefinitionPopoverGrid>
    )
}
