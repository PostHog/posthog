import { router } from 'kea-router'

import { IconEllipsis } from '@posthog/icons'
import { LemonButton, LemonMenu, Tooltip, lemonToast } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { base64Encode } from 'lib/utils'
import { getTextFromFile, selectFiles } from 'lib/utils/file-utils'
import { notebooksTableLogic } from 'scenes/notebooks/NotebooksTable/notebooksTableLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { NotebooksTable } from './NotebooksTable/NotebooksTable'

export const scene: SceneExport = {
    component: NotebooksScene,
    logic: notebooksTableLogic,
}

export function NotebooksScene(): JSX.Element {
    return (
        <SceneContent>
            <SceneTitleSection
                name="Notebooks"
                resourceType={{
                    type: 'notebook',
                }}
                actions={
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
                            <LemonButton size="small" data-attr="new-canvas" to={urls.canvas()} type="secondary">
                                New canvas
                            </LemonButton>
                        </Tooltip>
                        <AccessControlAction
                            resourceType={AccessControlResourceType.Notebook}
                            minAccessLevel={AccessControlLevel.Editor}
                        >
                            <LemonButton size="small" data-attr="new-notebook" to={urls.notebook('new')} type="primary">
                                New notebook
                            </LemonButton>
                        </AccessControlAction>
                    </>
                }
            />

            <NotebooksTable />
        </SceneContent>
    )
}
