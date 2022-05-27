import React from 'react'
import { LemonButtonWithPopup } from '.'
import { IconEllipsis } from '../icons'
import { PopupProps } from '../Popup/Popup'

export interface MoreProps extends Partial<Pick<PopupProps, 'overlay' | 'placement'>> {
    style?: React.CSSProperties
}

export function More({ overlay, placement = 'bottom-end', style }: MoreProps): JSX.Element {
    return (
        <LemonButtonWithPopup
            data-attr="more-button"
            icon={<IconEllipsis />}
            type="stealth"
            popup={{
                placement,
                actionable: true,
                overlay,
            }}
            disabled={!overlay}
            style={style}
        />
    )
}
