import { SceneExport } from 'scenes/sceneTypes'
import './NotebookScene.scss'
import { NotebooksTable } from './NotebooksTable/NotebooksTable'
import { LemonButton, LemonTag } from '@posthog/lemon-ui'
import { PageHeader } from 'lib/components/PageHeader'
import { urls } from 'scenes/urls'

export const scene: SceneExport = {
    component: NotebooksScene,
}

export function NotebooksScene(): JSX.Element {
    return (
        <div className="space-y-4">
            <PageHeader
                title={
                    <div className="flex items-center gap-2">
                        Notebooks
                        <LemonTag type="warning" className="uppercase">
                            Beta
                        </LemonTag>
                    </div>
                }
                buttons={
                    <LemonButton data-attr={'new-notebook'} to={urls.notebook('new')} type="primary">
                        New notebook
                    </LemonButton>
                }
            />

            <NotebooksTable />
        </div>
    )
}
