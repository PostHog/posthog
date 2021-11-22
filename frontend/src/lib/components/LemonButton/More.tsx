import React, { useState } from 'react'
import { LemonButton } from '.'
import { IconEllipsis } from '../icons'
import { PopupProps } from '../Popup/Popup'

export function More({ overlay }: Pick<PopupProps, 'overlay'>): JSX.Element {
    const [visible, setVisible] = useState(false)

    return (
        <LemonButton
            compact
            data-attr="more-button"
            icon={<IconEllipsis />}
            type="stealth"
            onClick={(e) => {
                setVisible((state) => !state)
                e.stopPropagation()
            }}
            popup={{
                visible,
                onClickOutside: () => setVisible(false),
                onClickInside: () => setVisible(false),
                placement: 'bottom-end',
                actionable: true,
                overlay,
            }}
        />
    )
}
