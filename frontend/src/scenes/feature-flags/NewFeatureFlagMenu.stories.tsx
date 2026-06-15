import { Meta } from '@storybook/react'

import { OverlayForNewFeatureFlagMenu } from './NewFeatureFlagMenu'

const meta: Meta<typeof OverlayForNewFeatureFlagMenu> = {
    title: 'Scenes-App/Feature Flags/New Feature Flag Menu',
    component: OverlayForNewFeatureFlagMenu,
}
export default meta

export function Default(): JSX.Element {
    return (
        <div className="w-80 rounded border p-1 bg-surface-primary">
            <OverlayForNewFeatureFlagMenu />
        </div>
    )
}
