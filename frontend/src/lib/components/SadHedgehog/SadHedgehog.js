import './SadHedgehog.scss'
import React from 'react'
import sadHedgehog from './assets/sad-hedgehog.svg'

export function SadHedgehog() {
    return (
        <div className="sad-hedgehog">
            <img src={sadHedgehog} alt="404" />
        </div>
    )
}
