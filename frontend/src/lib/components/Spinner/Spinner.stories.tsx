import React from 'react'
import { ComponentMeta } from '@storybook/react'

import { Spinner as Spinner } from './Spinner'

export default {
    title: 'Lemon UI/Spinner',
    component: Spinner,
} as ComponentMeta<typeof Spinner>

export function Default(): JSX.Element {
    return <Spinner />
}

export function Small(): JSX.Element {
    return <Spinner size="sm" />
}

export function Large(): JSX.Element {
    return <Spinner size="lg" />
}

export function Inverse(): JSX.Element {
    return (
        <div style={{ display: 'flex', background: 'black', width: 'fit-content', padding: 8 }}>
            <Spinner type="inverse" />
        </div>
    )
}
