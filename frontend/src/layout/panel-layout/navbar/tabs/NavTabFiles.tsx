import { useValues } from 'kea'

import { Spinner } from '@posthog/lemon-ui'

import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'

import { panelLayoutLogic } from '../../panelLayoutLogic'
import { ProjectTree } from '../../ProjectTree/ProjectTree'
import { projectTreeDataLogic } from '../../ProjectTree/projectTreeDataLogic'
import { projectTreeLogic } from '../../ProjectTree/projectTreeLogic'
import { FlatNavRecents } from './flat-nav/FlatNavRecents'
import { NavFilesMenu } from './NavFilesMenu'
import { FILES_STARRED_TREE_KEY, FILES_TREE_KEY, navFilesTabLogic } from './navFilesTabLogic'
import { NavTabSection } from './NavTabSection'

export function NavTabFiles(): JSX.Element {
    const { navExperimentActiveTab } = useValues(panelLayoutLogic)
    const { shortcutDataHasLoaded } = useValues(projectTreeDataLogic)
    const { searchTerm, folderRevealCount } = useValues(navFilesTabLogic)
    const { fullFileSystemFiltered: starredFiles } = useValues(
        projectTreeLogic({ key: FILES_STARRED_TREE_KEY, root: 'shortcuts://', shortcutScope: 'files' })
    )
    const showStarred = !searchTerm.trim() || !shortcutDataHasLoaded || starredFiles.length > 0

    return (
        <div
            className="flex flex-col h-full min-h-0 group/colorful-product-icons colorful-product-icons-true"
            data-attr="nav-panel-files"
        >
            <ScrollableShadows
                direction="vertical"
                className="flex-1 min-h-0"
                innerClassName="relative px-1"
                styledScrollbars
            >
                <div className="absolute top-0 right-1 z-10">
                    <NavFilesMenu />
                </div>
                {showStarred && (
                    <div className="pb-2">
                        <NavTabSection
                            label="Starred"
                            dataAttr="nav-files-starred-toggle"
                            key={`starred-${!!searchTerm.trim()}`}
                            actions={<span className="size-6.5 shrink-0" aria-hidden />}
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
                )}
                <NavTabSection
                    label="Files"
                    dataAttr="nav-files-project-toggle"
                    key={`files-${!!searchTerm.trim()}-${folderRevealCount}`}
                    actions={!showStarred && <span className="size-6.5 shrink-0" aria-hidden />}
                >
                    <ProjectTree
                        root="project://"
                        logicKey={FILES_TREE_KEY}
                        onlyTree
                        isActiveInPanel={navExperimentActiveTab === 'files'}
                    />
                </NavTabSection>
            </ScrollableShadows>
            <div className="max-h-1/3 overflow-y-auto px-2 border-t">
                <FlatNavRecents />
            </div>
        </div>
    )
}
