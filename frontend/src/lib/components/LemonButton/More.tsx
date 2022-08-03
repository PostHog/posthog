import React from 'react'
import { LemonButtonWithPopup } from '.'
import { IconEllipsis } from '../icons'
import { PopupProps } from '../Popup/Popup'

export interface MoreProps extends Partial<Pick<PopupProps, 'overlay' | 'placement'>> {
    style?: React.CSSProperties
    'data-tooltip'?: string
}

export function More({
    overlay,
    placement = 'bottom-end',
    style,
    'data-tooltip': dataTooltip,
}: MoreProps): JSX.Element {
    return (
        <LemonButtonWithPopup
            data-attr="more-button"
            data-tooltip={dataTooltip}
            icon={<IconEllipsis />}
            status="stealth"
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
