import { forwardRef } from 'react'

import { IconEllipsis } from '@posthog/icons'
import { ChipClose } from '@posthog/quill'

export const QuillBreakdownTagOptionsButton = forwardRef<HTMLButtonElement, React.ComponentProps<typeof ChipClose>>(
    function QuillBreakdownTagOptionsButton(props, ref): JSX.Element {
        return (
            <ChipClose
                ref={ref}
                aria-label="Breakdown options"
                data-attr="breakdown-tag-options"
                {...props}
                onClick={(e) => {
                    e.stopPropagation()
                    props.onClick?.(e)
                }}
            >
                <IconEllipsis />
            </ChipClose>
        )
    }
)
