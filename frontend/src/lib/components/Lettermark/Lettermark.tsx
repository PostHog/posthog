import React from 'react'
import './Lettermark.scss'

export function Lettermark({ name }: { name?: string | number | null }): JSX.Element {
    const initialLetter = name ? String(name)[0].toLocaleUpperCase() : '?'

    return <div className="Lettermark">{initialLetter}</div>
}
