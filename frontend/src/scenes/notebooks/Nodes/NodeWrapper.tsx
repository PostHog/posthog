import {
    NodeViewProps,
    Node,
    NodeViewWrapper,
    mergeAttributes,
    ReactNodeViewRenderer,
    ExtendedRegExpMatchArray,
    Attribute,
} from '@tiptap/react'
import { ReactNode, useCallback, useEffect, useMemo, useRef } from 'react'
import clsx from 'clsx'
import { IconDragHandle, IconLink, IconUnfoldLess, IconUnfoldMore } from 'lib/lemon-ui/icons'
import { LemonButton } from '@posthog/lemon-ui'
import './NodeWrapper.scss'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { BindLogic, useActions, useMountedLogic, useValues } from 'kea'
import { notebookLogic } from '../Notebook/notebookLogic'
import { useInView } from 'react-intersection-observer'
import { posthog } from 'posthog-js'
import { NotebookNodeType } from '~/types'
import { ErrorBoundary } from '~/layout/ErrorBoundary'
import { NotebookNodeContext, notebookNodeLogic } from './notebookNodeLogic'
import { uuid } from 'lib/utils'
import { posthogNodePasteRule } from './utils'

export interface NodeWrapperProps {
    title: string
    nodeType: NotebookNodeType
    children?: ReactNode | ((isEdit: boolean, isPreview: boolean) => ReactNode)
    href?: string | ((attributes: Record<string, any>) => string)

    // Sizing
    expandable?: boolean
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
}: NodeWrapperProps & NodeViewProps): JSX.Element {
    const { shortId } = useValues(notebookLogic)
    const mountedNotebookLogic = useMountedLogic(notebookLogic)
    const nodeId = useMemo(() => node.attrs.nodeId || uuid(), [node.attrs.nodeId])
    const nodeLogicProps = {
        nodeId,
        notebookLogic: mountedNotebookLogic,
        getPos: getPos,
    }
    const nodeLogic = useMountedLogic(notebookNodeLogic(nodeLogicProps))

    const { expanded } = useValues(nodeLogic)
    const { setExpanded } = useActions(nodeLogic)

    const [ref, inView] = useInView({ triggerOnce: true })
    const contentRef = useRef<HTMLDivElement | null>(null)

    // If resizeable is true then the node attr "height" is required
    const height = node.attrs.height

    useEffect(() => {
        if (selected) {
            setExpanded(true)
        }

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

    const parsedHref = typeof href === 'function' ? href(node.attrs) : href

    return (
        <NotebookNodeContext.Provider value={nodeLogic}>
            <BindLogic logic={notebookNodeLogic} props={nodeLogicProps}>
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
                                    <LemonButton
                                        onClick={() => setExpanded(!expanded)}
                                        size="small"
                                        className="flex-1"
                                        icon={<IconDragHandle className="cursor-move text-base shrink-0" />}
                                    >
                                        <span className="flex-1 cursor-pointer">{title}</span>
                                    </LemonButton>

                                    {parsedHref && <LemonButton size="small" icon={<IconLink />} to={parsedHref} />}

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
                                        expanded && resizeable && 'resize-y'
                                    )}
                                    // eslint-disable-next-line react/forbid-dom-props
                                    style={expanded && resizeable ? { height, minHeight } : {}}
                                    onMouseDown={onResizeStart}
                                >
                                    {children}
                                </div>
                            </>
                        )}
                    </ErrorBoundary>
                </NodeViewWrapper>
            </BindLogic>
        </NotebookNodeContext.Provider>
    )
}

export type CreatePostHogWidgetNodeOptions = NodeWrapperProps & {
    nodeType: NotebookNodeType
    Component: (props: NodeViewProps) => JSX.Element
    pasteOptions?: {
        find: string
        getAttributes: (match: ExtendedRegExpMatchArray) => Record<string, any> | null | undefined
    }
    attributes: Record<string, Partial<Attribute>>
}

// TODO: Correct return type
export const createPostHogWidgetNode = ({
    Component,
    pasteOptions,
    attributes,
    ...wrapperProps
}: CreatePostHogWidgetNodeOptions): any => {
    const WrappedComponent = (props: NodeViewProps): JSX.Element => {
        return (
            <NodeWrapper {...props} {...wrapperProps}>
                <Component {...props} />
            </NodeWrapper>
        )
    }

    return Node.create({
        name: wrapperProps.nodeType,
        group: 'block',
        atom: true,
        draggable: true,

        addAttributes() {
            return {
                height: {
                    default: wrapperProps.heightEstimate,
                },
                ...attributes,
            }
        },

        parseHTML() {
            return [
                {
                    tag: wrapperProps.nodeType,
                },
            ]
        },

        renderHTML({ HTMLAttributes }) {
            return [wrapperProps.nodeType, mergeAttributes(HTMLAttributes)]
        },

        addNodeView() {
            return ReactNodeViewRenderer(WrappedComponent)
        },

        addPasteRules() {
            return pasteOptions
                ? [
                      posthogNodePasteRule({
                          type: this.type,
                          ...pasteOptions,
                      }),
                  ]
                : []
        },
    })
}
