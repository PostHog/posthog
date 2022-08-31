import React from 'react'
import { ComponentMeta } from '@storybook/react'

import { Skeleton } from './Skeleton'
import { LemonLabel } from '../LemonLabel/LemonLabel'

export default {
    title: 'Lemon UI/Skeleton',
    component: Skeleton,
} as ComponentMeta<typeof Skeleton>

export function Default(): JSX.Element {
    return <Skeleton />
}

export function Sizes(): JSX.Element {
    return (
        <div className="space-y-2">
            <p>Skeletons are most easily styled with utility classNames</p>

            <LemonLabel>Default</LemonLabel>
            <Skeleton />
        </div>
    )
}
