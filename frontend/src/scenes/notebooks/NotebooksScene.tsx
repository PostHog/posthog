import { LemonButton } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { Shortcut } from 'lib/components/Shortcuts/Shortcut'
import { keyBinds } from 'lib/components/Shortcuts/shortcuts'
import { notebooksTableLogic } from 'scenes/notebooks/NotebooksTable/notebooksTableLogic'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { notebooksEmptyState } from 'products/notebooks/frontend/emptyState/notebooksEmptyState'

import { NotebooksTable } from './NotebooksTable/NotebooksTable'

export const scene: SceneExport = {
    component: NotebooksScene,
    logic: notebooksTableLogic,
    productKey: ProductKey.NOTEBOOKS,
    emptyState: notebooksEmptyState,
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
                    <AccessControlAction
                        resourceType={AccessControlResourceType.Notebook}
                        minAccessLevel={AccessControlLevel.Editor}
                    >
                        <Shortcut
                            name="NewNotebook"
                            keybind={[keyBinds.new]}
                            intent="New notebook"
                            interaction="click"
                            scope={Scene.Notebooks}
                        >
                            <LemonButton
                                size="small"
                                data-attr="new-notebook"
                                to={urls.notebook('new')}
                                type="primary"
                                tooltip="New notebook"
                            >
                                New notebook
                            </LemonButton>
                        </Shortcut>
                    </AccessControlAction>
                }
            />

            <NotebooksTable />
        </SceneContent>
    )
}
