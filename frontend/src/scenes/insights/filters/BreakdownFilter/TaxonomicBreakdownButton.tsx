import { IconPlusSmall } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { useState } from 'react'

import { taxonomicBreakdownFilterLogic } from './taxonomicBreakdownFilterLogic'
import { TaxonomicBreakdownPopover } from './TaxonomicBreakdownPopover'

interface TaxonomicBreakdownButtonProps {
    disabledReason?: string
}

export function TaxonomicBreakdownButton({ disabledReason }: TaxonomicBreakdownButtonProps): JSX.Element {
    const [open, setOpen] = useState(false)

    const { taxonomicBreakdownType } = useValues(taxonomicBreakdownFilterLogic)

    return (
        <TaxonomicBreakdownPopover open={open} setOpen={setOpen}>
            <LemonButton
                type="secondary"
                icon={<IconPlusSmall color="var(--primary)" />}
                data-attr="add-breakdown-button"
                onClick={() => setOpen(!open)}
                sideIcon={null}
                disabledReason={disabledReason}
            >
                {taxonomicBreakdownType === TaxonomicFilterGroupType.CohortsWithAllUsers
                    ? 'Add cohort'
                    : 'Add breakdown'}
            </LemonButton>
        </TaxonomicBreakdownPopover>
    )
}
