import clsx from 'clsx'
import { useState } from 'react'

interface XMLNode {
    type: 'element' | 'text' | 'attribute'
    name?: string
    value?: string
    attributes?: { [key: string]: string }
    children?: XMLNode[]
}

interface XMLViewerProps {
    children: string
    collapsed?: number
}

export function XMLViewer({ children: xmlContent, collapsed = 3 }: XMLViewerProps): JSX.Element {
    const parsedXML = parseXML(xmlContent)

    if (!parsedXML) {
        return <span className="font-mono whitespace-pre-wrap text-danger">Invalid XML content</span>
    }

    return (
        <div className="font-mono text-xs bg-accent-3000 rounded border p-2">
            {parsedXML.map((node, index) => (
                <XMLNodeDisplay key={index} node={node} depth={0} initialCollapsed={collapsed} />
            ))}
        </div>
    )
}

function XMLNodeDisplay({
    node,
    depth,
    initialCollapsed,
}: {
    node: XMLNode
    depth: number
    initialCollapsed: number
}): JSX.Element {
    const [isCollapsed, setIsCollapsed] = useState(depth >= initialCollapsed)
    const hasChildren = node.children && node.children.length > 0

    if (node.type === 'text') {
        if (!node.value || !node.value.trim()) {
            return <></>
        }

        return (
            <div className="text-muted whitespace-pre-wrap" style={{ marginLeft: `${depth * 16}px` }}>
                {node.value}
            </div>
        )
    }

    if (node.type === 'element') {
        const attributeString = node.attributes
            ? Object.entries(node.attributes)
                  .map(([key, value]) => ` ${key}="${value}"`)
                  .join('')
            : ''

        return (
            <div>
                <div
                    className={clsx(
                        'flex items-center gap-1',
                        hasChildren && 'cursor-pointer hover:bg-accent-3000 rounded'
                    )}
                    style={{
                        marginLeft: `${depth * 16}px`,
                        paddingLeft: hasChildren ? '4px' : '0',
                        paddingRight: hasChildren ? '4px' : '0',
                        marginRight: hasChildren ? '-4px' : '0',
                    }}
                    onClick={hasChildren ? () => setIsCollapsed(!isCollapsed) : undefined}
                >
                    <span className="text-primary">
                        {'<'}
                        <span className="text-danger font-semibold">{node.name}</span>
                        {attributeString && <span className="text-warning">{attributeString}</span>}
                        {!hasChildren ? ' />' : isCollapsed ? '>' : '>'}
                        {hasChildren && isCollapsed && (
                            <span
                                className="text-muted hover:text-primary cursor-pointer ml-1"
                                onClick={(e) => {
                                    e.stopPropagation()
                                    setIsCollapsed(false)
                                }}
                            >
                                ...
                            </span>
                        )}
                    </span>
                </div>

                {hasChildren && !isCollapsed && (
                    <>
                        {node.children?.map((child, index) => (
                            <XMLNodeDisplay
                                key={index}
                                node={child}
                                depth={depth + 1}
                                initialCollapsed={initialCollapsed}
                            />
                        ))}
                        <div className="text-primary" style={{ marginLeft: `${depth * 16}px` }}>
                            {'</'}
                            <span className="text-danger font-semibold">{node.name}</span>
                            {'>'}
                        </div>
                    </>
                )}
            </div>
        )
    }

    return <></>
}

function parseXML(xmlString: string): XMLNode[] | null {
    try {
        const parser = new DOMParser()
        // temp row in case of multiple root nodes
        const wrappedXML = `<temp_root>${xmlString}</temp_root>`
        const doc = parser.parseFromString(wrappedXML, 'text/xml')

        const parseError = doc.querySelector('parsererror')
        if (parseError) {
            return null
        }

        const result: XMLNode[] = []

        const processNode = (node: Node): XMLNode | null => {
            if (node.nodeType === Node.ELEMENT_NODE) {
                const element = node as Element
                const xmlNode: XMLNode = {
                    type: 'element',
                    name: element.tagName,
                    children: [],
                }

                // not actually needed for llma use case but could be useful to have?
                if (element.attributes.length > 0) {
                    xmlNode.attributes = {}
                    for (let i = 0; i < element.attributes.length; i++) {
                        const attr = element.attributes[i]
                        xmlNode.attributes[attr.name] = attr.value
                    }
                }

                for (let i = 0; i < element.childNodes.length; i++) {
                    const child = processNode(element.childNodes[i])
                    if (child) {
                        xmlNode.children!.push(child)
                    }
                }

                return xmlNode
            } else if (node.nodeType === Node.TEXT_NODE) {
                const text = node.textContent
                if (text && text.trim()) {
                    return {
                        type: 'text',
                        value: text,
                    }
                }
            }

            return null
        }

        const tempRoot = doc.documentElement
        if (tempRoot && tempRoot.tagName === 'temp_root') {
            for (let i = 0; i < tempRoot.childNodes.length; i++) {
                const child = processNode(tempRoot.childNodes[i])
                if (child) {
                    result.push(child)
                }
            }
        }

        return result
    } catch {
        return null
    }
}
