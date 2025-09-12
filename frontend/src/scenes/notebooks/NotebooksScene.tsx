import './NotebookScene.scss'

import { router } from 'kea-router'

import { IconEllipsis } from '@posthog/icons'
import { LemonButton, LemonMenu, Tooltip, lemonToast } from '@posthog/lemon-ui'

import { PageHeader } from 'lib/components/PageHeader'
import { base64Encode } from 'lib/utils'
import { getTextFromFile, selectFiles } from 'lib/utils/file-utils'
import { getAppContext } from 'lib/utils/getAppContext'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { NotebooksTable } from './NotebooksTable/NotebooksTable'

export const scene: SceneExport = {
    component: NotebooksScene,
}

export function NotebooksScene(): JSX.Element {
    return (
        <SceneContent forceNewSpacing>
            <PageHeader
                buttons={
                    <>
                        <LemonMenu
                            items={[
                                {
                                    label: 'Load from JSON',
                                    onClick: () => {
                                        void selectFiles({
                                            contentType: 'application/json',
                                            multiple: false,
                                        })
                                            .then((files) => getTextFromFile(files[0]))
                                            .then((text) => {
                                                const data = JSON.parse(text)
                                                if (data.type !== 'doc') {
                                                    throw new Error('Not a notebook')
                                                }

                                                // Looks like a notebook
                                                router.actions.push(
                                                    urls.canvas(),
                                                    {},
                                                    {
                                                        '🦔': base64Encode(text),
                                                    }
                                                )
                                            })
                                            .catch((e) => {
                                                lemonToast.error(e.message)
                                            })
                                    },
                                },
                            ]}
                        >
                            <LemonButton icon={<IconEllipsis />} size="small" />
                        </LemonMenu>
                        <Tooltip title="Like a Notebook but all your exploration is persisted to the URL for easy sharing.">
                            <LemonButton data-attr="new-canvas" to={urls.canvas()} type="secondary">
                                New canvas
                            </LemonButton>
                        </Tooltip>
                        <LemonButton
                            data-attr="new-notebook"
                            to={urls.notebook('new')}
                            type="primary"
                            accessControl={{
                                resourceType: AccessControlResourceType.Notebook,
                                minAccessLevel: AccessControlLevel.Editor,
                                userAccessLevel:
                                    getAppContext()?.resource_access_control?.[AccessControlResourceType.Notebook],
                            }}
                        >
                            New notebook
                        </LemonButton>
                    </>
                }
            />

            <SceneTitleSection
                name="Notebooks"
                description="Notebooks are a way to organize your work and share it with others."
                resourceType={{
                    type: 'notebook',
                }}
            />
            <SceneDivider />

            <NotebooksTable />
        </SceneContent>
    )
}
