import { BindLogic } from 'kea'
import { useRef } from 'react'

import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { LemonTreeRef } from 'lib/lemon-ui/LemonTree/LemonTree'

import { PROJECT_TREE_KEY, ProjectTree } from '~/layout/panel-layout/ProjectTree/ProjectTree'
import { projectTreeLogic } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'
import { TreeSearchField } from '~/layout/panel-layout/ProjectTree/TreeSearchField'

/**
 * The desktop app's "Files" navbar tab: the project tree (same logic key as the web app's
 * Files flyout panel), rendered inline in the sidepanel with its own search on top.
 */
export function NavTabFiles(): JSX.Element {
    const projectTreeLogicProps = { key: PROJECT_TREE_KEY, root: 'project://' }
    // The inline tree doesn't expose its LemonTree ref; search's ArrowDown-into-tree is a no-op here
    const treeRef = useRef<LemonTreeRef>(null)
    return (
        <div className="flex flex-col h-full min-h-0">
            <div className="px-2 pt-2 pb-1">
                <BindLogic logic={projectTreeLogic} props={projectTreeLogicProps}>
                    <TreeSearchField root="project://" placeholder="Search files" treeRef={treeRef} />
                </BindLogic>
            </div>
            <ScrollableShadows direction="vertical" className="flex-1 min-h-0" innerClassName="pb-2">
                <ProjectTree root="project://" logicKey={PROJECT_TREE_KEY} onlyTree showRecents />
            </ScrollableShadows>
        </div>
    )
}
