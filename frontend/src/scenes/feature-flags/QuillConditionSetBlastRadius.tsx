import { useActions, useValues } from 'kea'

import { IconInfo } from '@posthog/icons'
import { Button, Popover, PopoverContent, PopoverTrigger, Skeleton, Text } from '@posthog/quill'

import { clamp } from 'lib/utils/numbers'
import { pluralize } from 'lib/utils/strings'

import { BlastRadiusErrorMessage } from './BlastRadiusErrorMessage'
import { MATCHING_ESTIMATE_TOOLTIP } from './constants'
import {
    FeatureFlagGroupTypeWithSortKey,
    featureFlagReleaseConditionsLogic,
    isBlastRadiusErrorRetryable,
} from './featureFlagReleaseConditionsLogic'
import { QuillMatchingActorsLink } from './QuillMatchingActorsLink'

export function QuillConditionSetBlastRadius({
    group,
    resolvedGroupTypeIndex,
    targetName,
    singularTargetName,
}: {
    group: FeatureFlagGroupTypeWithSortKey
    resolvedGroupTypeIndex: number | null
    /** Plural aggregation target name, e.g. "users" or "organizations". */
    targetName: string
    singularTargetName: string
}): JSX.Element | null {
    const { affectedCounts, totalCounts, blastRadiusErrors } = useValues(featureFlagReleaseConditionsLogic)
    const { calculateBlastRadiusForCondition } = useActions(featureFlagReleaseConditionsLogic)

    const blastRadiusError = blastRadiusErrors[group.sort_key]
    const affected = affectedCounts[group.sort_key]
    const total = totalCounts[group.sort_key]

    if (blastRadiusError) {
        return (
            <div role="status" className="flex flex-wrap items-start gap-2">
                <Text size="xs" variant="destructive" render={<span className="min-w-0 flex-1" />}>
                    <BlastRadiusErrorMessage error={blastRadiusError} pluralName={targetName} />
                </Text>
                {isBlastRadiusErrorRetryable(blastRadiusError) && (
                    <Button
                        variant="outline"
                        onClick={() =>
                            calculateBlastRadiusForCondition(group.sort_key, group.properties, resolvedGroupTypeIndex)
                        }
                    >
                        Retry
                    </Button>
                )}
            </div>
        )
    }

    if (affected === undefined) {
        return (
            <div role="status" className="flex flex-col gap-1">
                <span className="sr-only">{`Calculating affected ${targetName}…`}</span>
                <Skeleton className="h-4 w-48" />
                <Skeleton className="h-4 w-56" />
                <Skeleton className="h-4 w-36" />
            </div>
        )
    }

    if (affected < 0 || total === undefined) {
        return null
    }

    const rolloutPercentage = Number.isNaN(group.rollout_percentage) ? 0 : (group.rollout_percentage ?? 100)
    const receivingFlag = Math.floor((affected * clamp(rolloutPercentage, 0, 100)) / 100)

    return (
        <div className="flex flex-col gap-1">
            <Text size="xs" variant="muted" render={<span className="flex items-center gap-1" />}>
                <span>
                    Filters match:{' '}
                    <b className="tabular-nums">{`~${pluralize(affected, singularTargetName, targetName)}`}</b>
                </span>
                {resolvedGroupTypeIndex == null && (
                    <Popover>
                        <PopoverTrigger render={<Button size="icon-xs" aria-label="About this estimate" />}>
                            <IconInfo />
                        </PopoverTrigger>
                        <PopoverContent className="max-w-80">
                            <Text size="xs" render={<div className="m-0" />}>
                                {MATCHING_ESTIMATE_TOOLTIP}
                            </Text>
                        </PopoverContent>
                    </Popover>
                )}
            </Text>
            <Text size="xs" variant="muted" render={<span />}>
                Rollout will be to{' '}
                <b className="tabular-nums">{`~${pluralize(receivingFlag, singularTargetName, targetName)}`}</b> -{' '}
                <b className="tabular-nums">{`${rolloutPercentage}%`}</b>
            </Text>
            <Text size="xs" render={<span />}>
                <QuillMatchingActorsLink
                    properties={group.properties}
                    resolvedGroupTypeIndex={resolvedGroupTypeIndex}
                    targetName={targetName}
                />
            </Text>
        </div>
    )
}
