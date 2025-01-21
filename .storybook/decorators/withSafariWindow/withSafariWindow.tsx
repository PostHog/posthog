import type { Decorator } from '@storybook/react'
import { SafariWindow } from './SafariWindow'


export const withSafariWindow: Decorator = (Story) => {
    return <div>
        <SafariWindow title="PostHog" />
        <Story />
    </div>
}
