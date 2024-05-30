import { IconEllipsis } from '@posthog/icons'

import { PopoverProps } from '../Popover/Popover'
import { LemonButtonWithDropdown } from '.'
import { LemonButtonProps } from './LemonButton'

export type MoreProps = Partial<Pick<PopoverProps, 'overlay' | 'placement'>> & LemonButtonProps

export function More({
    overlay,
    'data-attr': dataAttr,
    placement = 'bottom-end',
    ...buttonProps
}: MoreProps): JSX.Element {
    return (
        <LemonButtonWithDropdown
            aria-label="more"
            data-attr={dataAttr ?? 'more-button'}
            icon={<IconEllipsis />}
            dropdown={{
                placement: placement,
                actionable: true,
                overlay,
            }}
            size="small"
            {...buttonProps}
            disabled={!overlay}
        />
    )
}
