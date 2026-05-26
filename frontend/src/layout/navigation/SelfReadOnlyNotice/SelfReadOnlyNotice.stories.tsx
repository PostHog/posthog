import { Meta, StoryFn } from '@storybook/react'
import { useActions } from 'kea'
import { useEffect } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { SelfReadOnlyNotice } from './SelfReadOnlyNotice'

const meta: Meta<typeof SelfReadOnlyNotice> = {
    title: 'Layout/Self Read-Only Notice',
    component: SelfReadOnlyNotice,
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        // The global `withFeatureFlags` decorator reads this and resets it
        // between stories, so the read-only flag never leaks into other
        // stories' visual snapshots.
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
    // Also populate kea's featureFlagLogic directly. `parameters.featureFlags`
    // sets the persisted-flags window context for posthog-js, but the kea
    // store needs an explicit `setFeatureFlags` call to react in the same tick
    // the widget mounts.
    const { setFeatureFlags } = useActions(featureFlagLogic)
    useEffect(() => {
        try {
            localStorage.removeItem('self-read-only-notice-position')
        } catch {
            // storybook iframe may restrict storage access
        }
        setFeatureFlags([FEATURE_FLAGS.READ_ONLY_MODE], {
            [FEATURE_FLAGS.READ_ONLY_MODE]: true,
        })
    }, [setFeatureFlags])

    return (
        <>
            <FakeScene />
            <SelfReadOnlyNotice />
        </>
    )
}
