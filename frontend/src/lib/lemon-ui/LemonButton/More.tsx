import { LemonButtonWithDropdown } from '.'
import { IconEllipsis } from 'lib/lemon-ui/icons'
import { PopoverProps } from '../Popover/Popover'
import { LemonButtonWithDropdownProps } from './LemonButton'

export interface MoreProps extends Partial<Pick<PopoverProps, 'overlay' | 'placement'>> {
    style?: React.CSSProperties
    className?: string
    'data-attr'?: string
    onClick?: LemonButtonWithDropdownProps['onClick']
}

export function More({
    overlay,
    placement = 'bottom-end',
    className,
    'data-attr': dataAttr,
    onClick,
}: MoreProps): JSX.Element {
    return (
        <LemonButtonWithDropdown
            aria-label="more"
            data-attr={dataAttr ?? 'more-button'}
            icon={<IconEllipsis />}
            status="stealth"
            dropdown={{
                placement,
                actionable: true,
                overlay,
            }}
            size="small"
            className={className}
            disabled={!overlay}
            tooltip={tooltip}
            onClick={onClick}
        />
    )
}
