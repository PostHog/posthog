import { useValues } from 'kea'
import { useState } from 'react'

import { IconPlus } from '@posthog/icons'
import { Button, Text, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { taxonomicBreakdownFilterLogic } from './taxonomicBreakdownFilterLogic'
import { TaxonomicBreakdownPopover } from './TaxonomicBreakdownPopover'

export interface QuillTaxonomicBreakdownButtonProps {
    disabledReason?: React.ReactNode
}

export function QuillTaxonomicBreakdownButton({ disabledReason }: QuillTaxonomicBreakdownButtonProps): JSX.Element {
    const [open, setOpen] = useState(false)
    const { taxonomicBreakdownType } = useValues(taxonomicBreakdownFilterLogic)

    const button = (
        <Button
            variant="outline"
            data-attr="add-breakdown-button"
            onClick={() => setOpen(!open)}
            disabled={!!disabledReason}
        >
            <IconPlus />
            {taxonomicBreakdownType === TaxonomicFilterGroupType.CohortsWithAllUsers ? 'Cohort' : 'Breakdown'}
        </Button>
    )
    if (!disabledReason) {
        return (
            <TaxonomicBreakdownPopover open={open} setOpen={setOpen}>
                {button}
            </TaxonomicBreakdownPopover>
        )
    }
    // A reason with links (docs, SQL editor) can't live in a hover-only tooltip, so it shows inline.
    return typeof disabledReason === 'string' ? (
        <Tooltip>
            <TooltipTrigger render={button} />
            <TooltipContent>{disabledReason}</TooltipContent>
        </Tooltip>
    ) : (
        <div className="flex flex-col gap-1">
            {button}
            <Text size="xs" variant="muted" render={<div />}>
                {disabledReason}
            </Text>
        </div>
    )
}
