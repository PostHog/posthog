import React from 'react'
import { IconClose } from '../icons'
import { LemonButton } from '../LemonButton'

export interface PopupHeaderProps {
    title: string
    setPopupVisible: (visible: boolean) => void
}

export function PopupHeader({ title, setPopupVisible }: PopupHeaderProps): JSX.Element {
    return (
        <div className="PopupHeader">
            <h3>{title}</h3>
            <LemonButton onClick={() => setPopupVisible(false)} icon={<IconClose />} type="stealth" />
        </div>
    )
}
