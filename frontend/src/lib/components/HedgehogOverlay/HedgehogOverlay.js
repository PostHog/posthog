import './HedgehogOverlay.scss'
import React from 'react'

import sad from './assets/sad.svg'
import confused from './assets/confused.svg'
import dead from './assets/dead.svg'
import sick from './assets/sick.svg'
import excited from './assets/excited.svg'

const images = {
    sad,
    confused,
    dead,
    sick,
    excited,
}

export function HedgehogOverlay({ type = 'sad' }) {
    return (
        <div className="hedgehog-overlay">
            <img src={images[type] || 'sad'} alt="404" />
        </div>
    )
}
