import { Meta, StoryFn } from '@storybook/react'
import { useEffect } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'

import { SelfReadOnlyNotice } from './SelfReadOnlyNotice'

const meta: Meta<typeof SelfReadOnlyNotice> = {
    title: 'Layout/Self Read-Only Notice',
    component: SelfReadOnlyNotice,
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        // The global `withFeatureFlags` decorator handles this: it sets the
        // persisted-flags window context AND dispatches via featureFlagLogic
        // so already-mounted consumers react in the same tick the story renders.
        featureFlags: [FEATURE_FLAGS.READ_ONLY_MODE],
    },
}
export default meta

function FakeScene(): JSX.Element {
    return (
        <div className="h-screen w-screen bg-default p-8">
            <h1 className="text-2xl font-semibold">A pretend scene</h1>
            <p className="text-secondary mt-2">
                The floating Self Read-Only notice should be visible in the bottom-right corner.
            </p>
        </div>
    )
}

export const ReadOnly: StoryFn = () => {
    useEffect(() => {
        try {
            localStorage.removeItem('self-read-only-notice-position')
        } catch {
            // storybook iframe may restrict storage access
        }
    }, [])

    return (
        <>
            <FakeScene />
            <SelfReadOnlyNotice />
        </>
    )
}
