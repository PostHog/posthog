import type { Decorator } from '@storybook/react'
import { useAvailableFeatures } from '~/mocks/features'

import { KeaStory } from './kea-story'

export const withKea: Decorator = (Story) => {
    // Reset enabled enterprise features. Overwrite this line within your stories.
    useAvailableFeatures([])
    return (
        <KeaStory>
            <Story />
        </KeaStory>
    )
}
