import React from 'react'
import { LemonButtonWithPopup } from '.'
import { IconEllipsis } from '../icons'
import { PopupProps } from '../Popup/Popup'

interface MoreInterface extends Partial<Pick<PopupProps, 'overlay'>> {
    style?: React.CSSProperties
}

export function More({ overlay, style }: MoreInterface): JSX.Element {
    return (
        <LemonButtonWithPopup
            data-attr="more-button"
            icon={<IconEllipsis />}
            type="stealth"
            popup={{
                placement: 'bottom-end',
                actionable: true,
                overlay,
            }}
            disabled={!overlay}
            style={style}
        />
    )
}
