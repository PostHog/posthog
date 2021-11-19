import React from 'react'
import { ComponentMeta } from '@storybook/react'

import { Spinner as SpinnerComponent } from './Spinner'

export default {
    title: 'PostHog/Components/Spinner',
    component: SpinnerComponent,
    parameters: { options: { showPanel: true } },
} as ComponentMeta<typeof Spinner>

export function Spinner(): JSX.Element {
    return (
        <>
            <h2>Small – primary</h2>
            <SpinnerComponent size="sm" />
            <h2>Medium – primary (default)</h2>
            <SpinnerComponent />
            <h2>Large – primary</h2>
            <SpinnerComponent size="lg" />
            <h2>Medium – inverse</h2>
            <div style={{ display: 'flex', background: 'black', width: 'fit-content', padding: 8 }}>
                <SpinnerComponent type="inverse" />
            </div>
        </>
    )
}
