import type { Decorator } from '@storybook/react'

import { useAvailableFeatures } from '~/mocks/features'

import { KeaStory } from './kea-story'
import { StorySceneReady } from './StorySceneReady'

export const withKea: Decorator = (Story, context) => {
    // Reset enabled enterprise features. Overwrite this line within your stories.
    // eslint-disable-next-line react-hooks/rules-of-hooks
    useAvailableFeatures([])
    return (
        <KeaStory>
            {context.parameters.testOptions?.waitForSceneReady !== false ? (
                <StorySceneReady key={context.id} storyId={context.id}>
                    <Story />
                </StorySceneReady>
            ) : (
                <Story />
            )}
        </KeaStory>
    )
}
