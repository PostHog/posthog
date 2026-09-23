import { useActions, useValues } from 'kea'

import { Spinner } from '@posthog/lemon-ui'

import { panelLayoutLogic } from '../../panelLayoutLogic'
import { FolderNavigation } from '../../ProjectTree/FolderNavigation'
import { ProjectTree } from '../../ProjectTree/ProjectTree'
import { projectTreeDataLogic } from '../../ProjectTree/projectTreeDataLogic'
import { projectTreeLogic } from '../../ProjectTree/projectTreeLogic'
import { FlatNavRecents } from './flat-nav/FlatNavRecents'

export function NavTabFiles(): JSX.Element {
    const { navExperimentActiveTab, filesFolder } = useValues(panelLayoutLogic)
    const { openFolderInSidebar } = useActions(panelLayoutLogic)
    const { shortcutDataHasLoaded } = useValues(projectTreeDataLogic)
    const { fullFileSystemFiltered: starredFiles } = useValues(
        projectTreeLogic({ key: 'navbar-files-starred', root: 'shortcuts://', shortcutScope: 'files' })
    )
    return (
        <div className="flex flex-col h-full min-h-0">
            <div className="flex-1 min-h-0">
                <ProjectTree
                    key={filesFolder}
                    panelName="files"
                    root={`project://${filesFolder}`}
                    logicKey={filesFolder ? `navbar-files:${filesFolder}` : 'navbar-files'}
                    onFolderOpen={openFolderInSidebar}
                    searchPlaceholder="Search files"
                    showRecents
                    layout="inline"
                    beforeTree={
                        <>
                            <div className="px-1 pb-2">
                                <div className="px-2 pt-1 pb-1">
                                    <span className="text-xs font-semibold text-secondary">Starred</span>
                                </div>
                                {!shortcutDataHasLoaded ? (
                                    <Spinner className="m-2" />
                                ) : starredFiles.length > 0 ? (
                                    <ProjectTree
                                        root="shortcuts://"
                                        shortcutScope="files"
                                        logicKey="navbar-files-starred"
                                        onlyTree
                                        onFolderOpen={openFolderInSidebar}
                                        showShortcutHelp={false}
                                    />
                                ) : (
                                    <p className="text-xs text-tertiary px-2 py-1 mb-0">
                                        Star files or folders to keep them here.
                                    </p>
                                )}
                            </div>
                            <div className="px-1 pb-1">
                                <FolderNavigation folder={filesFolder} onOpen={openFolderInSidebar} />
                            </div>
                        </>
                    }
                    isActiveInPanel={navExperimentActiveTab === 'files'}
                />
            </div>
            <div className="max-h-1/3 overflow-y-auto px-2 border-t">
                <FlatNavRecents />
            </div>
        </div>
    )
}
