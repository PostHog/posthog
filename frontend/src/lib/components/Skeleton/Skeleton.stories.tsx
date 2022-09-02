import React from 'react'
import { ComponentMeta } from '@storybook/react'

import { Skeleton } from './Skeleton'
import { LemonLabel } from '../LemonLabel/LemonLabel'
import { LemonModal } from '../LemonModal'

export default {
    title: 'Lemon UI/Skeleton',
    component: Skeleton,
} as ComponentMeta<typeof Skeleton>

export function Default(): JSX.Element {
    return <Skeleton />
}

export function Presets(): JSX.Element {
    return (
        <div className="space-y-2">
            <p>Skeletons have a bunch of presets to help with simulating other LemonUI Components</p>

            <div className="flex items-center gap-2">
                <Skeleton.Circle />
                <Skeleton />
                <Skeleton.Button />
            </div>

            <p>Here is an example of "skeletoning" a LemonModal</p>

            <LemonModal
                isOpen
                onClose={() => {}}
                inline
                title="Loading..."
                footer={
                    <>
                        <Skeleton.Button />
                        <Skeleton.Button />
                    </>
                }
            >
                <div className="space-y-2">
                    <Skeleton width={'50%'} />
                    <Skeleton.Row repeat={3} />
                </div>
            </LemonModal>
        </div>
    )
}

export function Customisation(): JSX.Element {
    return (
        <div className="space-y-2 mb-2">
            <p>Skeletons are most easily styled with utility classNames</p>

            <LemonLabel>Default</LemonLabel>
            <Skeleton />
            <LemonLabel>Custom classNames</LemonLabel>
            <Skeleton className="h-10 rounded-lg" width={200} />
        </div>
    )
}
