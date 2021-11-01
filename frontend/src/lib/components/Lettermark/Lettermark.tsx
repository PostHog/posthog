import React from 'react'
import './Lettermark.scss'

export function Lettermark({ name }: { name: string | null | undefined }): JSX.Element {
    const initialLetter = name ? name[0].toLocaleUpperCase() : '?'

    return <div className="Lettermark">{initialLetter}</div>
}
