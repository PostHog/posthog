import { IconEllipsis } from '@posthog/icons'

import { PopoverProps } from '../Popover/Popover'
import { LemonButtonWithDropdown } from '.'
import { LemonButtonDropdown, LemonButtonProps } from './LemonButton'

export type MoreProps = Partial<Pick<PopoverProps, 'overlay' | 'placement'>> &
    LemonButtonProps & { dropdown?: Partial<LemonButtonDropdown> }

export function More({
    overlay,
    dropdown,
    'data-attr': dataAttr,
    placement = 'bottom-end',
    ...buttonProps
}: MoreProps): JSX.Element {
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
        />
    )
}
