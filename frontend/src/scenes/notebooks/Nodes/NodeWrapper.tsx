import {
    NodeViewProps,
    Node,
    NodeViewWrapper,
    mergeAttributes,
    ReactNodeViewRenderer,
    ExtendedRegExpMatchArray,
    Attribute,
} from '@tiptap/react'
import { ReactNode, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import clsx from 'clsx'
import { IconDragHandle, IconLink, IconUnfoldLess, IconUnfoldMore } from 'lib/lemon-ui/icons'
import { LemonButton } from '@posthog/lemon-ui'
import './NodeWrapper.scss'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { useMountedLogic, useValues } from 'kea'
import { notebookLogic } from '../Notebook/notebookLogic'
import { useInView } from 'react-intersection-observer'
import { posthog } from 'posthog-js'
import { NotebookNodeType } from '~/types'
import { ErrorBoundary } from '~/layout/ErrorBoundary'
import { NotebookNodeContext, notebookNodeLogic } from './notebookNodeLogic'
import { uuid } from 'lib/utils'
import { posthogNodePasteRule } from './utils'

export interface NodeWrapperProps extends NodeViewProps {
    title: string
    nodeType: NotebookNodeType
    children: ReactNode | ((isEdit: boolean, isPreview: boolean) => ReactNode)
    href?: string

    // Sizing
    resizeable?: boolean
    heightEstimate?: number | string
    minHeight?: number | string
}

export function NodeWrapper({
    title,
    nodeType,
    children,
    selected,
    href,
    heightEstimate = '4rem',
    resizeable = true,
    minHeight,
    node,
    getPos,
    updateAttributes,
}: NodeWrapperProps): JSX.Element {
    const { shortId } = useValues(notebookLogic)
    const mountedNotebookLogic = useMountedLogic(notebookLogic)
    const nodeId = useMemo(() => node.attrs.nodeId || uuid(), [node.attrs.nodeId])
    const nodeLogic = useMountedLogic(
        notebookNodeLogic({
            nodeId,
            notebookLogic: mountedNotebookLogic,
            getPos: getPos,
        })
    )

    const [expanded, setExpanded] = useState(false)

    const [ref, inView] = useInView({ triggerOnce: true })
    const contentRef = useRef<HTMLDivElement | null>(null)

    // If resizeable is true then the node attr "height" is required
    const height = node.attrs.height

    useEffect(() => {
        if (selected && shortId) {
            posthog.capture('notebook node selected', {
                node_type: nodeType,
                short_id: shortId,
            })
        }
    }, [selected])

    const onResizeStart = useCallback((): void => {
        if (!resizeable) {
            return
        }
        const initialHeightAttr = contentRef.current?.style.height
        const onResizedEnd = (): void => {
            window.removeEventListener('mouseup', onResizedEnd)
            // css resize sets the style attr so we check that to detect changes. Resize obsserver doesn't trigger for style changes
            const heightAttr = contentRef.current?.style.height
            if (heightAttr && heightAttr !== initialHeightAttr) {
                updateAttributes({
                    height: contentRef.current?.clientHeight,
                })
            }
        }

        window.addEventListener('mouseup', onResizedEnd)
    }, [resizeable, updateAttributes])

    return (
        <NotebookNodeContext.Provider value={nodeLogic}>
            <NodeViewWrapper
                ref={ref}
                as="div"
                className={clsx(nodeType, 'NotebookNode', {
                    'NotebookNode--selected': selected,
                })}
            >
                <ErrorBoundary>
                    {!inView ? (
                        <>
                            <div className="h-4" /> {/* Placeholder for the drag handle */}
                            <div style={{ height: heightEstimate }}>
                                <LemonSkeleton className="h-full" />
                            </div>
                        </>
                    ) : (
                        <>
                            <div className="NotebookNode__meta" data-drag-handle>
                                <IconDragHandle className="cursor-move text-base shrink-0" />
                                <span className="flex-1 cursor-pointer">{title}</span>

                                {href && <LemonButton size="small" icon={<IconLink />} to={href} />}

                                <LemonButton
                                    onClick={() => setExpanded(!expanded)}
                                    size="small"
                                    icon={expanded ? <IconUnfoldLess /> : <IconUnfoldMore />}
                                />
                            </div>
                            <div
                                ref={contentRef}
                                className={clsx(
                                    'NotebookNode__content flex flex-col relative z-0 overflow-hidden',
                                    resizeable && 'resize-y'
                                )}
                                // eslint-disable-next-line react/forbid-dom-props
                                style={resizeable ? { height, minHeight } : {}}
                                onMouseDown={onResizeStart}
                            >
                                {children}
                            </div>
                        </>
                    )}
                </ErrorBoundary>
            </NodeViewWrapper>
        </NotebookNodeContext.Provider>
    )
}

export type CreatePostHogWidgetNodeOptions = {
    nodeType: NotebookNodeType
    Component: (props: NodeWrapperProps) => JSX.Element
    defaultHeight: number
    pasteOptions?: {
        find: string
        getAttributes: (match: ExtendedRegExpMatchArray) => Record<string, any> | null | undefined
    }
    attributes: Record<string, Attribute>
}

// TODO: Correct return type
export const createPostHogWidgetNode = (props: CreatePostHogWidgetNodeOptions): any => {
    Node.create({
        name: props.nodeType,
        group: 'block',
        atom: true,
        draggable: true,

        addAttributes() {
            return {
                height: {
                    default: props.defaultHeight,
                },
                ...props.attributes,
            }
        },

        parseHTML() {
            return [
                {
                    tag: props.nodeType,
                },
            ]
        },

        renderHTML({ HTMLAttributes }) {
            return [props.nodeType, mergeAttributes(HTMLAttributes)]
        },

        addNodeView() {
            return ReactNodeViewRenderer(props.Component)
        },

        addPasteRules() {
            return props.pasteOptions
                ? [
                      posthogNodePasteRule({
                          type: this.type,
                          ...props.pasteOptions,
                      }),
                  ]
                : []
        },
    })
}
