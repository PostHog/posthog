import { LemonButtonWithPopup } from '.'
import { IconEllipsis } from '../icons'
import { PopupProps } from '../Popup/Popup'

export interface MoreProps extends Partial<Pick<PopupProps, 'overlay' | 'placement'>> {
    style?: React.CSSProperties
    'data-attr'?: string
}

export function More({ overlay, placement = 'bottom-end', 'data-attr': dataAttr }: MoreProps): JSX.Element {
    return (
        <LemonButtonWithPopup
            aria-label="more"
            data-attr={dataAttr ?? 'more-button'}
            icon={<IconEllipsis />}
            status="stealth"
            popup={{
                placement,
                actionable: true,
                overlay,
            }}
            size="small"
            disabled={!overlay}
        />
    )
}
