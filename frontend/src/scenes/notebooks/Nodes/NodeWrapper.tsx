import { NodeViewProps, NodeViewWrapper } from '@tiptap/react'
import { ReactNode, useEffect } from 'react'
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

export interface NodeWrapperProps extends NodeViewProps {
    title: string
    nodeType: NotebookNodeType
    children: ReactNode | ((isEdit: boolean, isPreview: boolean) => ReactNode)
    heightEstimate?: number | string
    href?: string
}

export function NodeWrapper({
    title,
    nodeType,
    children,
    selected,
    href,
    heightEstimate = '4rem',
}: NodeWrapperProps): JSX.Element {
    const { ready, shortId } = useValues(notebookLogic)
    const [ref, inView] = useInView({ triggerOnce: true })

    useEffect(() => {
        if (selected && shortId) {
            posthog.capture('notebook node selected', {
                node_type: nodeType,
                short_id: shortId,
            })
        }
    }, [selected])

    return (
        <NodeViewWrapper
            ref={ref}
            as="div"
            className={clsx(nodeType, 'NotebookNode flex flex-col gap-1 overflow-hidden', {
                'NotebookNode--selected': selected,
            })}
        >
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
                    <div className="flex flex-row gap-4 relative z-0">
                        <div className={clsx('relative mb-2 overflow-y-auto flex-1')}>{children}</div>
                    </div>
                </>
            )}
        </NodeViewWrapper>
    )
}
