import { LemonButtonWithDropdown } from '.'
import { forwardRef } from 'react'

import { IconEllipsis } from '@posthog/icons'

import { PopoverProps } from '../Popover/Popover'
import { LemonButtonDropdown, LemonButtonProps } from './LemonButton'

export type MoreProps = Partial<Pick<PopoverProps, 'overlay' | 'placement'>> &
    LemonButtonProps & { dropdown?: Partial<LemonButtonDropdown> }

export const More = forwardRef<HTMLButtonElement, MoreProps>(
    ({ overlay, dropdown, 'data-attr': dataAttr, placement = 'bottom-end', ...buttonProps }, ref) => {
        return (
            <LemonButtonWithDropdown
                aria-label="more"
                data-attr={dataAttr ?? 'more-button'}
                icon={<IconEllipsis />}
                dropdown={
                    {
                        placement: placement,
                        actionable: true,
                        ...dropdown,
                        overlay,
                    } as LemonButtonDropdown
                }
                size="small"
                {...buttonProps}
                disabled={!overlay}
                ref={ref}
            />
        )
    }
)
More.displayName = 'More'
