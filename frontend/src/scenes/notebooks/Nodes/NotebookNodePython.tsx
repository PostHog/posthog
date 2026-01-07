import { useMountedLogic, useValues } from 'kea'

import { IconCornerDownRight } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import { CodeEditorResizeable } from 'lib/monaco/CodeEditorResizable'
import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'

import { NotebookNodeAttributeProperties, NotebookNodeProps, NotebookNodeType } from '../types'
import { notebookNodeLogic } from './notebookNodeLogic'

type NotebookNodePythonAttributes = {
    code: string
    globalsUsed?: string[]
    globalsExportedWithTypes?: { name: string; type: string }[]
    globalsAnalysisHash?: string | null
}

const Component = ({ attributes }: NotebookNodeProps<NotebookNodePythonAttributes>): JSX.Element | null => {
    const nodeLogic = useMountedLogic(notebookNodeLogic)
    const { expanded } = useValues(nodeLogic)
    const exportedGlobals = attributes.globalsExportedWithTypes ?? []

    if (!expanded) {
        return null
    }

    return (
        <div data-attr="notebook-node-python" className="flex flex-col gap-2 p-3">
            <pre className="text-xs font-mono whitespace-pre-wrap">{attributes.code}</pre>
            {exportedGlobals.length > 0 ? (
                <div className="flex items-start flex-wrap gap-2 text-xs text-muted">
                    <span className="font-mono">
                        <IconCornerDownRight />
                    </span>
                    <div className="flex flex-wrap gap-1">
                        {exportedGlobals.map(({ name, type }) => (
                            <Tooltip key={name} title={`Type: ${type || 'unknown'}`}>
                                <span className="rounded border border-border px-1.5 py-0.5 text-xs font-mono bg-bg-light text-default">
                                    {name}
                                </span>
                            </Tooltip>
                        ))}
                    </div>
                </div>
            ) : null}
        </div>
    )
}

const Settings = ({
    attributes,
    updateAttributes,
}: NotebookNodeAttributeProperties<NotebookNodePythonAttributes>): JSX.Element => {
    return (
        <div className="p-3">
            <CodeEditorResizeable
                language="python"
                value={attributes.code}
                onChange={(value) => updateAttributes({ code: value ?? '' })}
                allowManualResize={false}
                minHeight={160}
            />
        </div>
    )
}

export const NotebookNodePython = createPostHogWidgetNode<NotebookNodePythonAttributes>({
    nodeType: NotebookNodeType.Python,
    titlePlaceholder: 'Python',
    Component,
    heightEstimate: 120,
    minHeight: 80,
    resizeable: true,
    startExpanded: true,
    attributes: {
        code: {
            default: '',
        },
        globalsUsed: {
            default: [],
        },
        globalsExportedWithTypes: {
            default: [],
        },
        globalsAnalysisHash: {
            default: null,
        },
    },
    Settings,
    settingsPlacement: 'inline',
    settingsIcon: 'pencil',
    serializedText: (attrs) => attrs.code,
})
