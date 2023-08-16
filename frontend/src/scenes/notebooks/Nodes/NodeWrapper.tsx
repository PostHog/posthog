import {
    Node,
    NodeViewWrapper,
    mergeAttributes,
    ReactNodeViewRenderer,
    ExtendedRegExpMatchArray,
    Attribute,
} from '@tiptap/react'
import { ReactNode, useCallback, useEffect, useRef } from 'react'
import clsx from 'clsx'
import { IconClose, IconDragHandle, IconLink, IconUnfoldLess, IconUnfoldMore } from 'lib/lemon-ui/icons'
import { LemonButton } from '@posthog/lemon-ui'
import './NodeWrapper.scss'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { BindLogic, useActions, useMountedLogic, useValues } from 'kea'
import { notebookLogic } from '../Notebook/notebookLogic'
import { useInView } from 'react-intersection-observer'
import { NotebookNodeType } from '~/types'
import { ErrorBoundary } from '~/layout/ErrorBoundary'
import { NotebookNodeContext, notebookNodeLogic } from './notebookNodeLogic'
import { uuid } from 'lib/utils'
import { posthogNodePasteRule } from './utils'
import { NotebookNodeAttributes, NotebookNodeViewProps, NotebookNodeWidget } from '../Notebook/utils'
import { NotebookNodeSettings } from './NotebookNodeSettings'

export interface NodeWrapperProps<T extends NotebookNodeAttributes> {
    title: string
    nodeType: NotebookNodeType
    children?: ReactNode | ((isEdit: boolean, isPreview: boolean) => ReactNode)
    href?: string | ((attributes: T) => string)

    // Sizing
    expandable?: boolean
    startExpanded?: boolean
    resizeable?: boolean
    heightEstimate?: number | string
    minHeight?: number | string
    /** If true the metadata area will only show when hovered if in editing mode */
    autoHideMetadata?: boolean
    widgets?: NotebookNodeWidget[]
}

export function NodeWrapper<T extends NotebookNodeAttributes>({
    title: defaultTitle,
    nodeType,
    children,
    selected,
    href,
    heightEstimate = '4rem',
    resizeable = true,
    startExpanded = false,
    expandable = true,
    autoHideMetadata = false,
    minHeight,
    node,
    getPos,
    updateAttributes,
    widgets = [],
    editor,
}: NodeWrapperProps<T> & NotebookNodeViewProps<T>): JSX.Element {
    const mountedNotebookLogic = useMountedLogic(notebookLogic)
    const { isEditable } = useValues(mountedNotebookLogic)
    const nodeId = node.attrs.nodeId

    const nodeLogicProps = {
        node,
        nodeType,
        nodeAttributes: node.attrs,
        updateAttributes,
        nodeId,
        notebookLogic: mountedNotebookLogic,
        getPos,
        title: defaultTitle,
        widgets,
        domNode: editor.view.nodeDOM(getPos()) as HTMLElement,
    }
    const nodeLogic = useMountedLogic(notebookNodeLogic(nodeLogicProps))
    const { title, expanded } = useValues(nodeLogic)
    const { setExpanded, deleteNode } = useActions(nodeLogic)

    useEffect(() => {
        if (startExpanded) {
            setExpanded(true)
        }
    }, [startExpanded])

    const [ref, inView] = useInView({ triggerOnce: true })
    const contentRef = useRef<HTMLDivElement | null>(null)

    // If resizeable is true then the node attr "height" is required
    const height = node.attrs.height ?? heightEstimate

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

    // Element is resizable if resizable is set to true. If expandable is set to true then is is only resizable if expanded is true
    const isResizeable = resizeable && (!expandable || expanded)

    return (
        <NotebookNodeContext.Provider value={nodeLogic}>
            <BindLogic logic={notebookNodeLogic} props={nodeLogicProps}>
                <NodeViewWrapper
                    ref={ref}
                    as="div"
                    className={clsx(nodeType, 'NotebookNode', {
                        'NotebookNode--selected': isEditable && selected,
                        'NotebookNode--auto-hide-metadata': autoHideMetadata,
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
                                        status="primary-alt"
                                        className="flex-1"
                                        icon={
                                            isEditable ? (
                                                <IconDragHandle className="cursor-move text-base shrink-0" />
                                            ) : undefined
                                        }
                                    >
                                        <span className="flex-1 cursor-pointer">{title}</span>
                                    </LemonButton>

                                    {parsedHref && <LemonButton size="small" icon={<IconLink />} to={parsedHref} />}

                                    {expandable && (
                                        <LemonButton
                                            onClick={() => setExpanded(!expanded)}
                                            size="small"
                                            icon={expanded ? <IconUnfoldLess /> : <IconUnfoldMore />}
                                        />
                                    )}

                                    {isEditable && (
                                        <LemonButton
                                            onClick={() => deleteNode()}
                                            size="small"
                                            status="danger"
                                            icon={<IconClose />}
                                        />
                                    )}
                                </div>
                                <div
                                    ref={contentRef}
                                    className={clsx(
                                        'NotebookNode__content flex flex-col relative z-0 overflow-hidden',
                                        isEditable && isResizeable && 'resize-y'
                                    )}
                                    // eslint-disable-next-line react/forbid-dom-props
                                    style={isResizeable ? { height, minHeight } : {}}
                                    onClick={!expanded ? () => setExpanded(true) : undefined}
                                    onMouseDown={onResizeStart}
                                >
                                    {children}
                                </div>
                            </>
                        )}
                    </ErrorBoundary>
                    {isEditable && selected && expanded ? <NotebookNodeSettings /> : null}
                </NodeViewWrapper>
            </BindLogic>
        </NotebookNodeContext.Provider>
    )
}

export type CreatePostHogWidgetNodeOptions<T extends NotebookNodeAttributes> = NodeWrapperProps<T> & {
    nodeType: NotebookNodeType
    Component: (props: NotebookNodeViewProps<T>) => JSX.Element | null
    pasteOptions?: {
        find: string
        getAttributes: (match: ExtendedRegExpMatchArray) => Promise<T | null | undefined> | T | null | undefined
    }
    attributes: Record<keyof T, Partial<Attribute>>
    widgets?: NotebookNodeWidget[]
}

export function createPostHogWidgetNode<T extends NotebookNodeAttributes>({
    Component,
    pasteOptions,
    attributes,
    ...wrapperProps
}: CreatePostHogWidgetNodeOptions<T>): Node {
    const WrappedComponent = (props: NotebookNodeViewProps<T>): JSX.Element => {
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
                height: {},
                nodeId: {
                    default: uuid,
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
                          editor: this.editor,
                          type: this.type,
                          ...pasteOptions,
                      }),
                  ]
                : []
        },
    })
}
