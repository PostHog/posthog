import { Meta, StoryFn } from '@storybook/react'

import { FeatureFlagFormLoadError } from './FeatureFlagFormLoadError'

const meta: Meta<typeof FeatureFlagFormLoadError> = {
    title: 'Scenes-App/Feature Flags/Feature Flag Form Load Error',
    component: FeatureFlagFormLoadError,
    args: { onRetry: () => {} },
}
export default meta

export const Default: StoryFn<typeof FeatureFlagFormLoadError> = (args) => <FeatureFlagFormLoadError {...args} />

// The scene is about this wide with the nav sidebar and a side panel open, where the actions wrap.
export const Narrow: StoryFn<typeof FeatureFlagFormLoadError> = (args) => (
    <div className="w-[520px]">
        <FeatureFlagFormLoadError {...args} />
    </div>
)
