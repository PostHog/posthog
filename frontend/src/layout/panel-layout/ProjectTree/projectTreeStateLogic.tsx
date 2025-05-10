import { actions, kea, key, path, props, reducers } from 'kea'

import { projectTreeStateLogicType } from '~/layout/panel-layout/ProjectTree/projectTreeStateLogicType'

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
    actions({
        setExpandedFolders: (expandedFolders: string[]) => ({ expandedFolders }),
    }),
    reducers(({ props }) => ({
        expandedFolders: [
            props.expandedFolders as string[],
            { setExpandedFolders: (_, { expandedFolders }) => expandedFolders },
        ],
    })),
])
