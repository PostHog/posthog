import { IconPlusSmall } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { useState } from 'react'

import { taxonomicBreakdownFilterLogic } from './taxonomicBreakdownFilterLogic'
import { TaxonomicBreakdownPopover } from './TaxonomicBreakdownPopover'

interface TaxonomicBreakdownButtonProps {
    isMixedSeries?: boolean
}

export function TaxonomicBreakdownButton({ isMixedSeries }: TaxonomicBreakdownButtonProps): JSX.Element {
    const [open, setOpen] = useState(false)

    const { taxonomicBreakdownType, breakdownDisabledReason } = useValues(taxonomicBreakdownFilterLogic)

    return (
        <TaxonomicBreakdownPopover open={open} setOpen={setOpen}>
            <LemonButton
                type="secondary"
                icon={<IconPlusSmall color="var(--primary)" />}
                data-attr="add-breakdown-button"
                onClick={() => setOpen(!open)}
                sideIcon={null}
                disabledReason={
                    isMixedSeries ? 'Breakdowns are not available for mixed series' : breakdownDisabledReason
                }
            >
                {taxonomicBreakdownType === TaxonomicFilterGroupType.CohortsWithAllUsers
                    ? 'Add cohort'
                    : 'Add breakdown'}
            </LemonButton>
        </TaxonomicBreakdownPopover>
    )
}
