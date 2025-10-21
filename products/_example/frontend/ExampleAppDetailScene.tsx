import { router } from 'kea-router'
import { useEffect, useState } from 'react'

import { LemonButton, LemonDivider } from '@posthog/lemon-ui'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { ExampleAppMockPerson } from './ExampleAppScene'
import { ExampleAppDetailLogicProps, exampleAppDetailLogic } from './exampleAppDetailLogic'

export const scene: SceneExport<ExampleAppDetailLogicProps> = {
    component: ExampleAppDetailScene,
    logic: exampleAppDetailLogic,
    paramsToProps: ({ params: { id } }) => ({ id: id && id !== 'new' ? id : 'new' }),
}

export function ExampleAppDetailScene(): JSX.Element {
    // TODO: Replace with logic
    const [isLoading, setIsLoading] = useState(true)
    const [item, setItem] = useState<ExampleAppMockPerson>({
        id: '1',
        name: 'Example Item',
        description: 'This is an example item',
        createdAt: '2021-01-01',
        updatedAt: '2021-01-01',
    })

    function handleSave(): void {
        setIsLoading(true)
        setTimeout(() => {
            setIsLoading(false)
            router.actions.push(urls.exampleApp())
            lemonToast.success('Item saved')
        }, 2000)
    }

    // TODO: Replace with logic
    useEffect(() => {
        setTimeout(() => {
            setIsLoading(false)
        }, 2000)
    }, [])

    // Wrap everything in a SceneContent component
    return (
        <SceneContent>
            <SceneTitleSection
                name={item.name}
                description={item.description}
                resourceType={{
                    type: sceneConfigurations[Scene.ExampleApp].iconType || 'default_icon_type',
                }}
                actions={
                    <>
                        <LemonButton size="small" type="secondary" to={urls.exampleApp()}>
                            Cancel
                        </LemonButton>
                        <LemonButton size="small" type="primary" onClick={handleSave}>
                            Save
                        </LemonButton>
                    </>
                }
                onNameChange={(name) => {
                    setItem({ ...item, name })
                }}
                onDescriptionChange={(description) => {
                    setItem({ ...item, description })
                }}
                canEdit
                isLoading={isLoading}
            />
            <SceneDivider />

            <SceneSection
                title="Details"
                description="Describe what the user is looking at in this section."
                isLoading={isLoading}
            >
                <p className="mb-0">
                    Sections with `SceneDivider`'s like this are useful for users to discern key areas of the page.
                </p>
            </SceneSection>
            <SceneDivider />
            <SceneSection title="Other details" isLoading={isLoading}>
                <p className="mb-0">Break down your content into sections.</p>
                <LemonDivider />
                <p className="mb-0">You can use dividers to separate sections.</p>
            </SceneSection>
        </SceneContent>
    )
}
