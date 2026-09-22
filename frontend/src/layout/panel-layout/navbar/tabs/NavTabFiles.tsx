import { useValues } from 'kea'

import { panelLayoutLogic } from '../../panelLayoutLogic'
import { ProjectTree } from '../../ProjectTree/ProjectTree'
import { FlatNavRecents } from './flat-nav/FlatNavRecents'

export function NavTabFiles(): JSX.Element {
    const { navExperimentActiveTab } = useValues(panelLayoutLogic)
    return (
        <div className="flex flex-col h-full min-h-0">
            <div className="flex-1 min-h-0">
                <ProjectTree
                    panelName="files"
                    root="project://"
                    logicKey="navbar-files"
                    searchPlaceholder="Search files"
                    showRecents
                    layout="inline"
                    isActiveInPanel={navExperimentActiveTab === 'files'}
                />
            </div>
            <div className="max-h-1/3 overflow-y-auto px-2 border-t">
                <FlatNavRecents />
            </div>
        </div>
    )
}
