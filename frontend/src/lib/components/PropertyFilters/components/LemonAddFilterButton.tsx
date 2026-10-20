import clsx from 'clsx'
import { forwardRef } from 'react'

import { IconPlusSmall } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'

export interface LemonAddFilterButtonProps {
    label: string
    labelClassName?: string
    pageKey: string
    size: 'xsmall' | 'small' | 'medium'
    onClick: () => void
}

export const LemonAddFilterButton = forwardRef<HTMLButtonElement, LemonAddFilterButtonProps>(
    function LemonAddFilterButton({ label, labelClassName, pageKey, size, onClick }, ref): JSX.Element {
        return (
            <LemonButton
                ref={ref}
                onClick={onClick}
                className={clsx('new-prop-filter', labelClassName)}
                data-attr={'new-prop-filter-' + pageKey}
                type="secondary"
                size={size}
                icon={<IconPlusSmall />}
                sideIcon={null}
            >
                {label}
            </LemonButton>
        )
    }
)
