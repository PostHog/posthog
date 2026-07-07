import { BindLogic, useActions, useValues } from 'kea'
import { useRef } from 'react'

import { LemonTreeRef } from 'lib/lemon-ui/LemonTree/LemonTree'
import { SceneExport } from 'scenes/sceneTypes'

import { ProjectTree } from '~/layout/panel-layout/ProjectTree/ProjectTree'
import { projectTreeLogic } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'
import { TreeFiltersDropdownMenu } from '~/layout/panel-layout/ProjectTree/TreeFiltersDropdownMenu'
import { TreeSearchField } from '~/layout/panel-layout/ProjectTree/TreeSearchField'
import { TreeSortDropdownMenu } from '~/layout/panel-layout/ProjectTree/TreeSortDropdownMenu'
import { HomeViewToggle } from '~/layout/scenes/HomeViewToggle'

import { FILES_SCENE_LOGIC_KEY, filesSceneLogic, filesSceneTreeProps } from './filesSceneLogic'

export const scene: SceneExport = {
    component: FilesScene,
    logic: filesSceneLogic,
}

export function FilesScene(): JSX.Element {
    const treeRef = useRef<LemonTreeRef>(null)
    const { searchTerm, sortMethod } = useValues(projectTreeLogic(filesSceneTreeProps))
    const { setSearchTerm, setSortMethod } = useActions(projectTreeLogic(filesSceneTreeProps))

    return (
        <div className="relative flex flex-col h-full overflow-hidden">
            <HomeViewToggle current="files" />
            <div className="absolute top-2 right-2 z-20 flex items-center gap-1">
                <div className="w-80">
                    <BindLogic logic={projectTreeLogic} props={filesSceneTreeProps}>
                        <TreeSearchField root="project://" placeholder="Search files" treeRef={treeRef} />
                    </BindLogic>
                </div>
                <TreeFiltersDropdownMenu searchTerm={searchTerm} setSearchTerm={setSearchTerm} />
                <TreeSortDropdownMenu sortMethod={sortMethod} setSortMethod={setSortMethod} />
            </div>
            <div className="flex-1 overflow-y-auto pt-14 pb-8">
                <div className="max-w-[960px] w-full mx-auto px-4">
                    <ProjectTree root="project://" onlyTree logicKey={FILES_SCENE_LOGIC_KEY} treeRef={treeRef} />
                </div>
            </div>
        </div>
    )
}
