import { useValues } from 'kea'
import { useState } from 'react'

import { IconPlusSmall } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { TaxonomicBreakdownPopover } from './TaxonomicBreakdownPopover'
import { taxonomicBreakdownFilterLogic } from './taxonomicBreakdownFilterLogic'

interface TaxonomicBreakdownButtonProps {
    disabledReason?: string
    size?: 'small' | 'medium'
}

export function TaxonomicBreakdownButton({ disabledReason, size }: TaxonomicBreakdownButtonProps): JSX.Element {
    const [open, setOpen] = useState(false)

    const { taxonomicBreakdownType } = useValues(taxonomicBreakdownFilterLogic)

    return (
        <TaxonomicBreakdownPopover open={open} setOpen={setOpen}>
            <LemonButton
                type="secondary"
                icon={<IconPlusSmall />}
                data-attr="add-breakdown-button"
                onClick={() => setOpen(!open)}
                sideIcon={null}
                disabledReason={disabledReason}
                size={size}
                tooltipDocLink={
                    taxonomicBreakdownType === TaxonomicFilterGroupType.CohortsWithAllUsers
                        ? 'https://posthog.com/docs/product-analytics/trends/breakdowns#cohorts-and-breakdowns'
                        : 'https://posthog.com/docs/product-analytics/trends/breakdowns'
                }
            >
                {taxonomicBreakdownType === TaxonomicFilterGroupType.CohortsWithAllUsers
                    ? 'Add cohort'
                    : 'Add breakdown'}
            </LemonButton>
        </TaxonomicBreakdownPopover>
    )
}
