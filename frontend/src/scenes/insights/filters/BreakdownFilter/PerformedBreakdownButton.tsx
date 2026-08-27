import { useActions, useValues } from 'kea'
import { ReactElement } from 'react'

import { IconPlusSmall } from '@posthog/icons'

import { TaxonomicFilterGroup, TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'
import { FEATURE_FLAGS } from 'lib/constants'

import { hogql } from '~/queries/utils'

import { taxonomicBreakdownFilterLogic } from './taxonomicBreakdownFilterLogic'

/** A HogQL breakdown splitting people into those who performed the event or action in the
 * last 30 days and those who didn't. The trailing comment is the tag's display label. */
export function performedBreakdownHogQL(
    value: string | number,
    groupType: TaxonomicFilterGroupType,
    name: string
): string {
    const match =
        groupType === TaxonomicFilterGroupType.Actions
            ? hogql`matchesAction(${Number(value)})`
            : hogql`event = ${String(value)}`
    return (
        `if(person_id IN (SELECT person_id FROM events WHERE ${match} AND timestamp > now() - INTERVAL 30 DAY), ` +
        `'Did perform', 'Did not perform') -- Performed ${name}`
    )
}

interface PerformedBreakdownButtonProps {
    disabledReason?: ReactElement | string
    size?: 'small' | 'medium'
}

export function PerformedBreakdownButton({ disabledReason, size }: PerformedBreakdownButtonProps): JSX.Element | null {
    const { addBreakdown } = useActions(taxonomicBreakdownFilterLogic)
    const { featureFlags, hasDataWarehouseSeries } = useValues(taxonomicBreakdownFilterLogic)

    // A performed breakdown compiles to a person_id subquery over the events table, which a warehouse series has no key for
    if (!featureFlags[FEATURE_FLAGS.BEHAVIORAL_PROPERTY_FILTER] || hasDataWarehouseSeries) {
        return null
    }

    return (
        <TaxonomicPopover
            groupType={TaxonomicFilterGroupType.Events}
            groupTypes={[TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.Actions]}
            value={null}
            onChange={(value, groupType, item) =>
                value != null &&
                addBreakdown(performedBreakdownHogQL(value, groupType, item?.name || String(value)), {
                    type: TaxonomicFilterGroupType.HogQLExpression,
                } as TaxonomicFilterGroup)
            }
            type="secondary"
            placeholder="Performed"
            placeholderClass=""
            icon={<IconPlusSmall />}
            sideIcon={null}
            size={size}
            disabledReason={disabledReason}
            data-attr="add-performed-breakdown-button"
        />
    )
}
