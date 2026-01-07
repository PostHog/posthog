import { useMountedLogic, useValues } from 'kea'
import { useMemo, useState } from 'react'

import { IconCornerDownRight } from '@posthog/icons'

import { JSONContent } from 'lib/components/RichContentEditor/types'
import { Popover } from 'lib/lemon-ui/Popover/Popover'
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

type PythonNodeSummary = {
    nodeId: string
    code: string
    globalsUsed: string[]
    pythonIndex: number
}

type VariableUsage = {
    nodeId: string
    pythonIndex: number
}

const collectPythonNodes = (content?: JSONContent | null): PythonNodeSummary[] => {
    if (!content || typeof content !== 'object') {
        return []
    }

    const nodes: PythonNodeSummary[] = []

    const walk = (node: any): void => {
        if (!node || typeof node !== 'object') {
            return
        }
        if (node.type === NotebookNodeType.Python) {
            const attrs = node.attrs ?? {}
            nodes.push({
                nodeId: attrs.nodeId ?? '',
                code: typeof attrs.code === 'string' ? attrs.code : '',
                globalsUsed: Array.isArray(attrs.globalsUsed) ? attrs.globalsUsed : [],
                pythonIndex: nodes.length + 1,
            })
        }
        if (Array.isArray(node.content)) {
            node.content.forEach(walk)
        }
    }

    walk(content)
    return nodes
}

const VariableUsageOverlay = ({
    name,
    type,
    usages,
}: {
    name: string
    type: string
    usages: VariableUsage[]
}): JSX.Element => {
    const groupedUsageEntries = usages.reduce<Record<string, VariableUsage>>((acc, usage) => {
        if (!acc[usage.nodeId]) {
            acc[usage.nodeId] = usage
        }
        return acc
    }, {})
    const sortedUsageEntries = Object.values(groupedUsageEntries).sort((a, b) => a.pythonIndex - b.pythonIndex)

    return (
        <div className="p-2 text-xs max-w-[320px]">
            <div className="flex items-center justify-between gap-2">
                <span className="font-semibold text-default font-mono">{name}</span>
                <span className="text-muted">Type: {type || 'unknown'}</span>
            </div>
            {sortedUsageEntries.length > 0 ? (
                <div className="mt-2">
                    <div className="text-muted text-[10px] uppercase tracking-wide">Used in</div>
                    <div className="mt-1 space-y-1 max-h-48 overflow-y-auto">
                        {sortedUsageEntries.map((usage) => (
                            <div key={`usage-${usage.pythonIndex}`} className="text-muted">
                                Python cell {usage.pythonIndex}
                            </div>
                        ))}
                    </div>
                </div>
            ) : (
                <div className="mt-2 text-muted">Not used in later cells.</div>
            )}
        </div>
    )
}

const VariableDependencyBadge = ({
    name,
    type,
    usages,
}: {
    name: string
    type: string
    usages: VariableUsage[]
}): JSX.Element => {
    const [popoverVisible, setPopoverVisible] = useState(false)
    const isUsedDownstream = usages.length > 0

    return (
        <Popover
            onClickOutside={() => setPopoverVisible(false)}
            visible={popoverVisible}
            placement="bottom-start"
            overlay={<VariableUsageOverlay name={name} type={type} usages={usages} />}
        >
            <button
                type="button"
                onClick={() => setPopoverVisible((visible) => !visible)}
                className="rounded border border-border px-1.5 py-0.5 text-xs font-mono bg-bg-light text-default hover:bg-bg-light/80 transition"
            >
                <span className={isUsedDownstream ? 'font-semibold' : undefined}>{name}</span>
                {isUsedDownstream ? <span className="text-muted"> → {usages.length}</span> : null}
            </button>
        </Popover>
    )
}

const Component = ({ attributes }: NotebookNodeProps<NotebookNodePythonAttributes>): JSX.Element | null => {
    const nodeLogic = useMountedLogic(notebookNodeLogic)
    const { expanded, notebookLogic } = useValues(nodeLogic)
    const { content } = useValues(notebookLogic)
    const exportedGlobals = attributes.globalsExportedWithTypes ?? []

    const pythonNodes = useMemo(() => collectPythonNodes(content), [content])
    const currentNodeIndex = pythonNodes.findIndex((node) => node.nodeId === attributes.nodeId)
    const downstreamNodes = currentNodeIndex >= 0 ? pythonNodes.slice(currentNodeIndex + 1) : []

    const usageByVariable = useMemo(() => {
        const usageMap: Record<string, VariableUsage[]> = {}

        exportedGlobals.forEach(({ name }) => {
            const usages = downstreamNodes.flatMap((node) =>
                node.globalsUsed.includes(name)
                    ? [
                          {
                              nodeId: node.nodeId,
                              pythonIndex: node.pythonIndex,
                          },
                      ]
                    : []
            )

            usageMap[name] = usages
        })

        return usageMap
    }, [downstreamNodes, exportedGlobals])

    if (!expanded) {
        return null
    }

    return (
        <div data-attr="notebook-node-python" className="flex h-full flex-col gap-2">
            <div className="p-3 overflow-y-auto h-full">
                <pre className="text-xs font-mono whitespace-pre-wrap">{attributes.code}</pre>
            </div>
            {exportedGlobals.length > 0 ? (
                <div className="flex items-start flex-wrap gap-2 text-xs text-muted border-t p-2">
                    <span className="font-mono mt-1">
                        <IconCornerDownRight />
                    </span>
                    <div className="flex flex-wrap gap-1">
                        {exportedGlobals.map(({ name, type }) => (
                            <VariableDependencyBadge
                                key={name}
                                name={name}
                                type={type}
                                usages={usageByVariable[name] ?? []}
                            />
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
