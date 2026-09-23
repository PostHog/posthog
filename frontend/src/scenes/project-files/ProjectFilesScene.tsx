import { router } from 'kea-router'

import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { FolderNavigation } from '~/layout/panel-layout/ProjectTree/FolderNavigation'
import { ProjectTree } from '~/layout/panel-layout/ProjectTree/ProjectTree'
import { SceneContent } from '~/layout/scenes/components/SceneContent'

export interface ProjectFilesSceneProps {
    folder?: string
}

export const scene: SceneExport<ProjectFilesSceneProps> = {
    component: ProjectFilesScene,
    paramsToProps: ({ searchParams }) => ({
        folder: typeof searchParams.folder === 'string' ? searchParams.folder : '',
    }),
}

export function ProjectFilesScene({ folder = '' }: ProjectFilesSceneProps): JSX.Element {
    return (
        <SceneContent className="h-full min-h-0 flex-1 overflow-hidden gap-y-2 pb-1">
            <div className="flex shrink-0 items-center gap-2">
                <h1 className="sr-only">Files</h1>
                <FolderNavigation folder={folder} onOpen={(path) => router.actions.push(urls.projectFiles(path))} />
            </div>
            <div className="min-h-0 min-w-0 flex-1 overflow-hidden border rounded">
                <ProjectTree
                    key={folder}
                    onlyTree
                    disableScroll={false}
                    root={`project://${folder}`}
                    logicKey={`project-files:${folder}`}
                    onFolderOpen={(path) => router.actions.push(urls.projectFiles(path))}
                />
            </div>
        </SceneContent>
    )
}
