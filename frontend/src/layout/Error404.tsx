import React from 'react'
import { HedgehogOverlay } from 'lib/components/HedgehogOverlay/HedgehogOverlay'

export function Error404(): JSX.Element {
    return (
        <div>
            <h2>Error 404</h2>
            <p>Page not found.</p>
            <HedgehogOverlay type="sad" />
        </div>
    )
}
