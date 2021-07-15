import './HedgehogOverlay.scss'
import React from 'react'

import sad from './assets/sad.svg'

const images: Record<string, string> = {
    sad,
}

export function HedgehogOverlay({ type = 'sad' }: { type: string }): JSX.Element {
    return (
        <div className="hedgehog-overlay">
            <img src={images[type] || 'sad'} alt="404" />
        </div>
    )
}
