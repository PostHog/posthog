import { Meta } from '@storybook/react'

import { LemonLabel } from 'lib/lemon-ui/LemonLabel/LemonLabel'
import { LemonModal } from 'lib/lemon-ui/LemonModal'

import { LemonSkeleton } from './LemonSkeleton'

const meta: Meta<typeof LemonSkeleton> = {
    title: 'Lemon UI/Lemon Skeleton',
    component: LemonSkeleton,
    parameters: {
        docs: {
            description: {
                component: `
[Related Figma area](https://www.figma.com/file/Y9G24U4r04nEjIDGIEGuKI/PostHog-Design-System-One?node-id=2028%3A841)

Skeleton screens are used to indicate that a screen is loading, are perceived as being shorter in duration when compared against a blank screen (our control) and a spinner — but not by much`,
            },
        },
        testOptions: {
            waitForLoadersToDisappear: false,
        },
    },
    tags: ['autodocs'],
}
export default meta

export function Default(): JSX.Element {
    return <LemonSkeleton />
}

export function Presets(): JSX.Element {
    return (
        <div className="deprecated-space-y-2">
            <p>Skeletons have a bunch of presets to help with simulating other LemonUI Components</p>

            <div className="flex items-center gap-2">
                <LemonSkeleton.Circle />
                <LemonSkeleton />
                <LemonSkeleton.Button />
            </div>

            <p>Here is an example of "skeletoning" a LemonModal</p>

            <LemonModal
                isOpen
                onClose={() => {}}
                inline
                title="Loading..."
                footer={
                    <>
                        <LemonSkeleton.Button />
                        <LemonSkeleton.Button />
                    </>
                }
            >
                <div className="deprecated-space-y-2">
                    <LemonSkeleton className="w-1/2 h-4" />
                    <LemonSkeleton.Row repeat={3} />
                </div>
            </LemonModal>
        </div>
    )
}

export function Customisation(): JSX.Element {
    return (
        <div className="deprecated-space-y-2 mb-2">
            <p>Skeletons are most easily styled with utility classNames</p>

            <LemonLabel>Default</LemonLabel>
            <LemonSkeleton />
            <LemonLabel>Custom classNames</LemonLabel>
            <LemonSkeleton className="h-10 rounded-lg w-1/3" />
        </div>
    )
}

export function Repeat(): JSX.Element {
    return (
        <div className="deprecated-space-y-2 p-2 rounded">
            <p>
                Skeletons can be easily repeated multiple times using the <b>repeat</b> property
            </p>

            <LemonSkeleton repeat={5} />

            <p>
                Add the <b>fade</b> property to progressively fade out the repeated skeletons
            </p>

            <LemonSkeleton repeat={5} fade />
        </div>
    )
}
