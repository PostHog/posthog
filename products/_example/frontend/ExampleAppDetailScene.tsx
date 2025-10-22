import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconTrash } from '@posthog/icons'
import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { SceneActivityIndicator } from 'lib/components/Scenes/SceneUpdateActivityInfo'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import {
    ScenePanel,
    ScenePanelActionsSection,
    ScenePanelDivider,
    ScenePanelInfoSection,
} from '~/layout/scenes/SceneLayout'
import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { UserBasicType } from '~/types'

import { ExampleAppDetailLogicProps, exampleAppDetailLogic } from './exampleAppDetailLogic'

export const scene: SceneExport<ExampleAppDetailLogicProps> = {
    component: ExampleAppDetailScene,
    logic: exampleAppDetailLogic,
    paramsToProps: ({ params: { id }, searchParams }) => ({
        id: id && id !== 'new' ? id : 'new',
        tabId: searchParams.tabId || 'default',
    }),
}

export function ExampleAppDetailScene({ id, tabId }: ExampleAppDetailLogicProps): JSX.Element {
    const logic = exampleAppDetailLogic({ id, tabId })
    const { person, isLoading, canSave, isNewPerson } = useValues(logic)
    const { updateName, updateDescription, savePerson, deletePerson } = useActions(logic)
    const { user } = useValues(userLogic)
    const [deletePersonModalVisible, setDeletePersonModalVisible] = useState(false)
    return (
        <>
            <SceneContent>
                <SceneTitleSection
                    name={person?.name || ''}
                    description={person?.description || ''}
                    resourceType={{
                        type: sceneConfigurations[Scene.ExampleApp].iconType || 'default_icon_type',
                    }}
                    actions={
                        <>
                            <LemonButton size="small" type="secondary" to={urls.exampleApp()}>
                                Cancel
                            </LemonButton>
                            <LemonButton
                                size="small"
                                type="primary"
                                onClick={savePerson}
                                disabledReason={!canSave ? 'No changes to save' : undefined}
                            >
                                Save
                            </LemonButton>
                        </>
                    }
                    onNameChange={(name) => {
                        updateName(name)
                    }}
                    onDescriptionChange={(description) => {
                        updateDescription(description)
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
                </SceneSection>
            </SceneContent>

            {/* Scene panels are useful actions that would be too much for the title section */}
            <ScenePanel>
                <ScenePanelInfoSection>
                    {/* Scene tags, SceneFile, SceneActivityIndicator can go here! */}

                    {user && (
                        <SceneActivityIndicator at={person?.createdAt} by={user as UserBasicType} prefix="Created" />
                    )}
                </ScenePanelInfoSection>
                <ScenePanelDivider />

                <ScenePanelActionsSection>
                    {!isNewPerson && (
                        <ButtonPrimitive
                            variant="danger"
                            menuItem
                            onClick={() => {
                                setDeletePersonModalVisible(true)
                            }}
                        >
                            <IconTrash /> Delete
                        </ButtonPrimitive>
                    )}
                </ScenePanelActionsSection>
            </ScenePanel>

            <LemonModal
                title="Delete person"
                onClose={() => setDeletePersonModalVisible(false)}
                isOpen={deletePersonModalVisible}
                footer={
                    <>
                        <LemonButton type="secondary" onClick={() => setDeletePersonModalVisible(false)}>
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="secondary"
                            status="danger"
                            loading={isLoading}
                            onClick={() => {
                                deletePerson()
                                setDeletePersonModalVisible(false)
                            }}
                        >
                            Delete person
                        </LemonButton>
                    </>
                }
            >
                <p>Are you sure you want to delete "{person?.name}"? This action cannot be undone.</p>
            </LemonModal>
        </>
    )
}
