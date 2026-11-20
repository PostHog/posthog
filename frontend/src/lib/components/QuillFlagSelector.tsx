import { Button, Popover, PopoverContent, PopoverTrigger } from '@posthog/quill'

import { closesIntoLemonPopover } from 'lib/components/QuillSurface/closesIntoLemonPopover'
import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { TaxonomicFilterLogicProps } from 'lib/components/TaxonomicFilter/types'

export function QuillFlagSelector({
    open,
    onOpenChange,
    label,
    disabledReason,
    taxonomicFilterLogicProps,
}: {
    open: boolean
    onOpenChange: (open: boolean) => void
    label: string
    disabledReason: string | undefined
    taxonomicFilterLogicProps: TaxonomicFilterLogicProps
}): JSX.Element {
    return (
        <Popover
            open={open}
            onOpenChange={(next, details) => {
                if (closesIntoLemonPopover(next, details)) {
                    details.cancel()
                    return
                }

                onOpenChange(next)
            }}
        >
            <PopoverTrigger render={<Button variant="outline" disabledReason={disabledReason} />}>
                {label}
            </PopoverTrigger>
            <PopoverContent side="right" align="start" className="w-auto p-0">
                {/* The filter is Lemon, so it keeps Lemon's colors inside the quill popover. */}
                <div data-not-quill>
                    <TaxonomicFilter {...taxonomicFilterLogicProps} />
                </div>
            </PopoverContent>
        </Popover>
    )
}
