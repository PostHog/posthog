import './HedgehogOverlay.scss'
import React from 'react'

import sad from './assets/sad.svg'

const images = {
    sad,
}

export function HedgehogOverlay({ type = 'sad' }) {
    return (
        <div className="hedgehog-overlay">
            <img src={images[type] || 'sad'} alt="404" />
        </div>
    )
}
