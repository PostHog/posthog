import { useValues } from 'kea'
import { router } from 'kea-router'

import { LemonTabs } from '@posthog/lemon-ui'

import { notebooksTableLogic } from 'scenes/notebooks/NotebooksTable/notebooksTableLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { notebooksEmptyState } from 'products/notebooks/frontend/emptyState/notebooksEmptyState'
import { ReusableWidgetCatalog } from 'products/notebooks/frontend/ReusableWidgetCatalog/ReusableWidgetCatalog'

import { NewNotebookButton } from './NewNotebookButton'
import { NotebooksSceneMenuBar } from './NotebooksSceneMenuBar'
import { NotebooksTable } from './NotebooksTable/NotebooksTable'

export const scene: SceneExport = {
    component: NotebooksScene,
    logic: notebooksTableLogic,
    productKey: ProductKey.NOTEBOOKS,
    emptyState: notebooksEmptyState,
}

export function NotebooksScene(): JSX.Element {
    const { searchParams } = useValues(router)
    const activeTab = searchParams.tab === 'widgets' ? 'widgets' : 'notebooks'

    return (
        <SceneContent>
            <NotebooksSceneMenuBar />
            <SceneTitleSection
                name="Notebooks"
                resourceType={{
                    type: 'notebook',
                }}
                actions={<NewNotebookButton />}
            />
            <LemonTabs
                activeKey={activeTab}
                sceneInset
                tabs={[
                    {
                        key: 'notebooks',
                        label: 'Notebooks',
                        link: urls.notebooks(),
                        content: <NotebooksTable />,
                    },
                    {
                        key: 'widgets',
                        label: 'Reusable widgets',
                        link: `${urls.notebooks()}?tab=widgets`,
                        content: <ReusableWidgetCatalog />,
                    },
                ]}
            />
        </SceneContent>
    )
}
