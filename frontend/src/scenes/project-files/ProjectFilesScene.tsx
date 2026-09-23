import { LemonButton } from '@posthog/lemon-ui'

import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { ProjectTree } from '~/layout/panel-layout/ProjectTree/ProjectTree'
import { SceneContent } from '~/layout/scenes/components/SceneContent'

export interface ProjectFilesSceneProps {
    folder?: string
}

export const scene: SceneExport<ProjectFilesSceneProps> = {
    component: ProjectFilesScene,
    paramsToProps: ({ searchParams }) => ({
        folder: typeof searchParams.folder === 'string' ? searchParams.folder.replace(/^\/+|\/+$/g, '') : '',
    }),
}

export function ProjectFilesScene({ folder = '' }: ProjectFilesSceneProps): JSX.Element {
    return (
        <SceneContent className="h-full min-h-0 flex-1 overflow-hidden gap-y-2 pb-1">
            <div className="flex shrink-0 items-center gap-2">
                <h1 className="m-0 min-w-0 flex-1 truncate text-lg font-semibold" title={folder || 'Project'}>
                    {folder || 'Project'}
                </h1>
                {folder && (
                    <LemonButton
                        size="small"
                        to={urls.projectFiles(folder.split('/').slice(0, -1).join('/'))}
                        aria-label="Parent folder"
                        tooltip="Parent folder"
                    >
                        ..
                    </LemonButton>
                )}
            </div>
            <div className="min-h-0 min-w-0 flex-1 overflow-hidden border rounded">
                <ProjectTree
                    key={folder}
                    onlyTree
                    disableScroll={false}
                    root={`project://${folder}`}
                    logicKey={`project-files:${folder}`}
                />
            </div>
        </SceneContent>
    )
}
