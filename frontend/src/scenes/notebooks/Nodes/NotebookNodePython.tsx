import { useMountedLogic, useValues } from 'kea'

import { CodeEditorResizeable } from 'lib/monaco/CodeEditorResizable'
import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'

import { NotebookNodeAttributeProperties, NotebookNodeProps, NotebookNodeType } from '../types'
import { notebookNodeLogic } from './notebookNodeLogic'

type NotebookNodePythonAttributes = {
    code: string
    globalsUsed?: string[]
    globalsExported?: string[]
}

const Component = ({ attributes }: NotebookNodeProps<NotebookNodePythonAttributes>): JSX.Element | null => {
    const nodeLogic = useMountedLogic(notebookNodeLogic)
    const { expanded } = useValues(nodeLogic)

    if (!expanded) {
        return null
    }

    return (
        <div data-attr="notebook-node-python">
            <pre>We should run this code: {attributes.code}</pre>
            <pre>Globals used: {JSON.stringify(attributes.globalsUsed)}</pre>
            <pre>Globals exported: {JSON.stringify(attributes.globalsExported)}</pre>
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
        globalsExported: {
            default: [],
        },
    },
    Settings,
    settingsPlacement: 'inline',
    settingsIcon: 'pencil',
    serializedText: (attrs) => attrs.code,
})
