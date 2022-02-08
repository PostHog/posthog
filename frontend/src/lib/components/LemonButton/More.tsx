import React from 'react'
import { LemonButtonWithPopup } from '.'
import { IconEllipsis } from '../icons'
import { PopupProps } from '../Popup/Popup'

export function More({ overlay }: Pick<PopupProps, 'overlay'>): JSX.Element {
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
        />
    )
}
