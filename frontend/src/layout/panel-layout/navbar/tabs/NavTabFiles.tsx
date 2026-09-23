import { useValues } from 'kea'

import { Spinner } from '@posthog/lemon-ui'

import { panelLayoutLogic } from '../../panelLayoutLogic'
import { ProjectTree } from '../../ProjectTree/ProjectTree'
import { projectTreeDataLogic } from '../../ProjectTree/projectTreeDataLogic'
import { projectTreeLogic } from '../../ProjectTree/projectTreeLogic'
import { FlatNavRecents } from './flat-nav/FlatNavRecents'
import { FILES_STARRED_TREE_KEY, FILES_TREE_KEY, navFilesTabLogic } from './navFilesTabLogic'
import { NavTabSection } from './NavTabSection'

export function NavTabFiles(): JSX.Element {
    const { navExperimentActiveTab } = useValues(panelLayoutLogic)
    const { shortcutDataHasLoaded } = useValues(projectTreeDataLogic)
    const { searchTerm } = useValues(navFilesTabLogic)
    const { fullFileSystemFiltered: starredFiles } = useValues(
        projectTreeLogic({ key: FILES_STARRED_TREE_KEY, root: 'shortcuts://', shortcutScope: 'files' })
    )
    return (
        <div className="flex flex-col h-full min-h-0">
            <div className="flex-1 min-h-0">
                <ProjectTree
                    panelName="files"
                    root="project://"
                    logicKey={FILES_TREE_KEY}
                    searchPlaceholder="Filter files"
                    showRecents
                    layout="inline"
                    beforeTree={
                        (!searchTerm.trim() || !shortcutDataHasLoaded || starredFiles.length > 0) && (
                            <div className="px-1 pb-2">
                                <NavTabSection
                                    label="Starred"
                                    dataAttr="nav-files-starred-toggle"
                                    key={`starred-${!!searchTerm.trim()}`}
                                >
                                    {!shortcutDataHasLoaded ? (
                                        <Spinner className="m-2" />
                                    ) : starredFiles.length > 0 ? (
                                        <ProjectTree
                                            root="shortcuts://"
                                            shortcutScope="files"
                                            logicKey={FILES_STARRED_TREE_KEY}
                                            onlyTree
                                            showShortcutHelp={false}
                                        />
                                    ) : (
                                        <p className="text-xs text-tertiary px-2 py-1 mb-0">
                                            Star files or folders to keep them here.
                                        </p>
                                    )}
                                </NavTabSection>
                            </div>
                        )
                    }
                    renderTree={(tree) => (
                        <div className="px-1">
                            <NavTabSection
                                label="Files"
                                dataAttr="nav-files-project-toggle"
                                key={`files-${!!searchTerm.trim()}`}
                            >
                                {tree}
                            </NavTabSection>
                        </div>
                    )}
                    isActiveInPanel={navExperimentActiveTab === 'files'}
                />
            </div>
            <div className="max-h-1/3 overflow-y-auto px-2 border-t">
                <FlatNavRecents />
            </div>
        </div>
    )
}
