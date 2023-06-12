import { Attributes, NodeViewProps, NodeViewWrapper } from '@tiptap/react'
import { ReactNode, useEffect, useRef } from 'react'
import clsx from 'clsx'
import { IconDragHandle, IconLink } from 'lib/lemon-ui/icons'
import { Link } from '@posthog/lemon-ui'
import './NodeWrapper.scss'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { useValues } from 'kea'
import { notebookLogic } from '../Notebook/notebookLogic'
import { useInView } from 'react-intersection-observer'
import { posthog } from 'posthog-js'
import { NotebookNodeType } from '~/types'
import { ErrorBoundary } from '~/layout/ErrorBoundary'

export interface NodeWrapperProps extends NodeViewProps {
    title: string
    nodeType: NotebookNodeType
    children: ReactNode | ((isEdit: boolean, isPreview: boolean) => ReactNode)
    heightEstimate?: number | string
    href?: string
    resizeable?: boolean
}

export function NodeWrapper({
    title,
    nodeType,
    children,
    selected,
    href,
    heightEstimate = '4rem',
    resizeable = true,
    node,
    updateAttributes,
}: NodeWrapperProps): JSX.Element {
    const { ready, shortId } = useValues(notebookLogic)
    const [ref, inView] = useInView({ triggerOnce: true })
    const contentRef = useRef<HTMLDivElement | null>(null)
    const contentHeightRef = useRef<string>()

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

    const checkResize = (): void => {
        if (!resizeable) {
            return
        }
        // css resize sets the style attr so we check that to detect changes. Resize obsserver doesn't trigger for style changes
        const heightAttr = contentRef.current?.style.height
        if (heightAttr && heightAttr !== contentHeightRef.current) {
            contentHeightRef.current = heightAttr
            updateAttributes({
                height: contentRef.current?.clientHeight,
            })
        }
    }

    return (
        <NodeViewWrapper
            ref={ref}
            as="div"
            className={clsx(nodeType, 'NotebookNode flex flex-col gap-1 overflow-hidden', {
                'NotebookNode--selected': selected,
            })}
        >
            <ErrorBoundary>
                {!ready || !inView ? (
                    <>
                        <div className="h-4" /> {/* Placeholder for the drag handle */}
                        <div style={{ height: heightEstimate }}>
                            <LemonSkeleton className="h-full" />
                        </div>
                    </>
                ) : (
                    <>
                        <div
                            className={clsx(
                                'NotebookNode__meta flex items-center justify-between text-xs truncate text-muted-alt',
                                {
                                    'font-semibold': selected,
                                }
                            )}
                            data-drag-handle
                        >
                            <div className="shrink-0">
                                <IconDragHandle className="cursor-move text-base shrink-0" />
                                <span>{title}</span>
                            </div>
                            <div className="shrink-0 flex gap-4">
                                {href && (
                                    <Link to={href}>
                                        <IconLink /> Link
                                    </Link>
                                )}
                            </div>
                        </div>
                        <div
                            ref={contentRef}
                            className={clsx('relative z-0 overflow-hidden min-h-40', resizeable && 'resize-y')}
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{ height }}
                            onMouseUp={() => checkResize()}
                        >
                            {children}
                        </div>
                    </>
                )}
            </ErrorBoundary>
        </NodeViewWrapper>
    )
}

export function getNodeWrapperAttributes(): Attributes {
    return {
        height: {
            default: undefined,
            keepOnSplit: true,
        },
    }
}
