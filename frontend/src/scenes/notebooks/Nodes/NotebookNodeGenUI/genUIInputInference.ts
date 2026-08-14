import { JSONContent } from 'lib/components/RichContentEditor/types'

import { NotebookNodeType } from '../../types'
import { buildNotebookDependencyGraph } from '../notebookNodeContent'
import { validateGenUIInputs } from './genUIInputs'

const MAX_INFERRED_FRAME_COUNT = 4

export type GenUIInputInference = {
    names: string[]
    serialized: string
}

export function inferGenUIInputs(
    content: JSONContent | null | undefined,
    nodeId: string,
    prompt: string,
    configuredInputs: string
): GenUIInputInference {
    const configured = validateGenUIInputs(configuredInputs)
    const dependencyNodes = buildNotebookDependencyGraph(content).nodes
    const targetIndex = dependencyNodes.findIndex(
        (node) => node.nodeId === nodeId && node.nodeType === NotebookNodeType.GenUI
    )

    if (targetIndex === -1) {
        const names = configured.error ? [] : configured.names
        return { names, serialized: names.join(', ') }
    }

    const availableNames = dependencyNodes
        .slice(0, targetIndex)
        .filter((node) => node.nodeType === NotebookNodeType.SQLV2 || node.nodeType === NotebookNodeType.PythonV2)
        .flatMap((node) => node.exports)
        .filter((name, index, names) => names.indexOf(name) === index)
    const availableNameSet = new Set(availableNames)
    const mentionedNames = (prompt.match(/[A-Za-z_][A-Za-z0-9_]*/g) ?? []).filter(
        (name, index, names) => availableNameSet.has(name) && names.indexOf(name) === index
    )
    const configuredNames = configured.error ? [] : configured.names.filter((name) => availableNameSet.has(name))
    const names = (
        mentionedNames.length > 0
            ? mentionedNames
            : configuredNames.length > 0
              ? configuredNames
              : availableNames.slice(-MAX_INFERRED_FRAME_COUNT)
    ).slice(0, MAX_INFERRED_FRAME_COUNT)

    return { names, serialized: names.join(', ') }
}
