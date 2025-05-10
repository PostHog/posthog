import { actions, connect, kea, key, listeners, path, props, reducers } from 'kea'

import { projectTreeLogic } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'
import { projectTreeStateLogicType } from '~/layout/panel-layout/ProjectTree/projectTreeStateLogicType'
import { joinPath, splitPath } from '~/layout/panel-layout/ProjectTree/utils'

import type { projectTreeStateLogicType } from './projectTreeStateLogicType'

export interface ProjectTreeStateLogicProps {
    uniqueId: string
    expandedFolders?: string[]
}

let uniqueIndex = 0

export function getUniqueProjectTreeId(): string {
    return String(uniqueIndex++)
}

export const projectTreeStateLogic = kea<projectTreeStateLogicType>([
    path(['layout', 'panel-layout', 'ProjectTree', 'projectTreeStateLogic']),
    props({ uniqueId: '' } as ProjectTreeStateLogicProps),
    key(({ uniqueId }) => uniqueId),
    connect(() => ({
        actions: [projectTreeLogic, ['loadFolder']],
        values: [projectTreeLogic, ['folderStates']],
    })),
    actions({
        setExpandedFolders: (expandedFolders: string[]) => ({ expandedFolders }),
        expandProjectFolder: (path: string) => ({ path }),
    }),
    reducers(({ props }) => ({
        expandedFolders: [
            props.expandedFolders as string[],
            { setExpandedFolders: (_, { expandedFolders }) => expandedFolders },
        ],
    })),
    listeners(({ values }) => ({
        expandProjectFolder: ({ path }) => {
            const expandedSet = new Set(values.expandedFolders)
            const allFolders = splitPath(path).slice(0, -1)
            const allFullFolders = allFolders.map((_, index) => joinPath(allFolders.slice(0, index + 1)))
            const nonExpandedFolders = allFullFolders.filter((f) => !expandedSet.has('project-folder/' + f))
            for (const folder of nonExpandedFolders) {
                if (values.folderStates[folder] !== 'loaded' && values.folderStates[folder] !== 'loading') {
                    actions.loadFolder(folder)
                }
            }
            actions.setExpandedFolders([
                ...values.expandedFolders,
                ...nonExpandedFolders.map((f) => 'project-folder/' + f),
            ])
        },
    })),
])
