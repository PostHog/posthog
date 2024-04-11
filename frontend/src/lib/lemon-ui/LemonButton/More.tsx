import { IconEllipsis } from '@posthog/icons'

import { PopoverProps } from '../Popover/Popover'
import { LemonButtonWithDropdown } from '.'
import { LemonButtonProps, LemonButtonWithDropdownProps } from './LemonButton'

export type MoreProps = Partial<Pick<PopoverProps, 'overlay' | 'placement'>> &
    LemonButtonProps & {
        'data-attr'?: string
        onClick?: LemonButtonWithDropdownProps['onClick']
    }

export function More({
    overlay,
    placement = 'bottom-end',
    'data-attr': dataAttr,
    onClick,
    ...buttonProps
}: MoreProps): JSX.Element {
    return (
        <LemonButtonWithDropdown
            aria-label="more"
            data-attr={dataAttr ?? 'more-button'}
            icon={<IconEllipsis />}
            dropdown={{
                placement,
                actionable: true,
                overlay,
            }}
            size="small"
            {...buttonProps}
            disabled={!overlay}
            onClick={onClick}
        />
    )
}
