import React from 'react'
import { ComponentMeta } from '@storybook/react'

import { Spinner as Spinner } from './Spinner'
import { LemonButton } from '@posthog/lemon-ui'

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

export function Monocolor(): JSX.Element {
    return (
        <div className="bg-default p-4">
            <Spinner size="lg" monocolor className="text-white" />
        </div>
    )
}

export function InButtons(): JSX.Element {
    return (
        <div className="flex gap-2 items-center">
            <LemonButton type="primary" loading>
                Primary
            </LemonButton>
            <LemonButton type="secondary" loading>
                Secondary Button
            </LemonButton>

            <LemonButton type="secondary" status="danger" loading>
                Secondary Danger
            </LemonButton>
        </div>
    )
}
