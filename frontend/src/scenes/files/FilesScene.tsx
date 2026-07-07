import { SceneExport } from 'scenes/sceneTypes'

import { ProjectTree } from '~/layout/panel-layout/ProjectTree/ProjectTree'
import { HomeViewToggle } from '~/layout/scenes/HomeViewToggle'

export const scene: SceneExport = {
    component: FilesScene,
}

export function FilesScene(): JSX.Element {
    return (
        <div className="relative flex flex-col h-full overflow-hidden">
            <HomeViewToggle current="files" />
            <div className="flex-1 overflow-y-auto pt-14 pb-8">
                <div className="max-w-[960px] w-full mx-auto px-4">
                    <ProjectTree root="project://" onlyTree logicKey="files-scene" />
                </div>
            </div>
        </div>
    )
}
