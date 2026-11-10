import { forwardRef, ReactNode } from 'react'

import { LemonTag, LemonTagType } from '@posthog/lemon-ui'

export interface ChipButtonProps {
    children: ReactNode
    onClick?: () => void
    type?: LemonTagType
    icon?: JSX.Element
    'aria-label'?: string
    'data-attr'?: string
}

// A tag that acts, so clickable chips keep the size of the chips beside them and still take keyboard focus.
export const ChipButton = forwardRef<HTMLButtonElement, ChipButtonProps>(function ChipButton(
    { children, onClick, type = 'default', icon, 'aria-label': ariaLabel, 'data-attr': dataAttr, ...rest },
    ref
): JSX.Element {
    return (
        <button
            ref={ref}
            type="button"
            onClick={onClick}
            aria-label={ariaLabel}
            data-attr={dataAttr}
            className="inline-flex rounded"
            {...rest}
        >
            <LemonTag type={type} icon={icon} weight="normal" className="cursor-pointer">
                {children}
            </LemonTag>
        </button>
    )
})
