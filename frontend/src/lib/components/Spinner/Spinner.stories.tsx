import React from 'react'
import { ComponentMeta } from '@storybook/react'

import { Spinner as Spinner } from './Spinner'

export default {
    title: 'Components/Spinner',
    component: Spinner,
} as ComponentMeta<typeof Spinner>

export const Default = (): JSX.Element => <Spinner />

export const Small = (): JSX.Element => <Spinner size="sm" />

export const Large = (): JSX.Element => <Spinner size="lg" />

export const Inverse = (): JSX.Element => (
    <div style={{ display: 'flex', background: 'black', width: 'fit-content', padding: 8 }}>
        <Spinner type="inverse" />
    </div>
)
