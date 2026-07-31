import type { Meta, StoryObj } from '@storybook/react'

import { sceneLogic } from 'scenes/sceneLogic'
import { emptySceneParams } from 'scenes/scenes'

import { SceneTitleSection } from './SceneTitleSection'

// The alpha/beta tag beside a scene title is derived from the active scene (via `sceneLogic`),
// not from a prop, so each story sets the scene before rendering.

const meta: Meta = {
    title: 'Scenes-App/Scene title section',
    parameters: { layout: 'fullscreen', viewMode: 'story' },
}
export default meta

type Story = StoryObj

function renderForScene(sceneId: string, name: string): JSX.Element {
    sceneLogic.mount()
    sceneLogic.actions.setScene(sceneId, undefined, emptySceneParams, 'push')
    return (
        <div className="bg-primary p-4">
            <SceneTitleSection name={name} resourceType={{ type: 'blank' }} />
        </div>
    )
}

export const AlphaProduct: Story = {
    render: () => renderForScene('Links', 'Links'),
}

export const BetaProduct: Story = {
    render: () => renderForScene('Inbox', 'Inbox'),
}

export const StableProduct: Story = {
    render: () => renderForScene('FeatureFlags', 'Feature flags'),
}
