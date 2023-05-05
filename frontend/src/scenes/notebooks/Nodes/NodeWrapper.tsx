import { NodeViewProps, NodeViewWrapper } from '@tiptap/react'
import { ReactNode } from 'react'
import clsx from 'clsx'
import { IconDragHandle, IconLink } from 'lib/lemon-ui/icons'
import { Link } from '@posthog/lemon-ui'
import './NodeWrapper.scss'

export interface NodeWrapperProps extends NodeViewProps {
    title: string
    className: string
    children: ReactNode | ((isEdit: boolean, isPreview: boolean) => ReactNode)
    preview?: ReactNode // Minified preview mode to show in small screen situations and unexpanded modes. If not defined, children are mounted and rendered.
    href?: string
}

export function NodeWrapper({ title, className, children, preview, selected, href }: NodeWrapperProps): JSX.Element {
    const content = selected ? children : preview ?? children

    return (
        <NodeViewWrapper as="div" className={clsx(className, 'NotebookNode flex flex-col gap-1 overflow-hidden')}>
            <div className="flex items-center justify-between text-xs text-muted-alt truncate" data-drag-handle>
                <div className="shrink-0">
                    <IconDragHandle className="text-muted-alt cursor-move text-base shrink-0" />
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
            <div className="flex flex-row gap-4">
                <div
                    // className={clsx('relative mb-2 flex-1 overflow-y-auto')}
                    className={clsx('relative mb-2 overflow-y-auto flex-1', {
                        'border-primary border-2 rounded': selected,
                    })}
                >
                    {content}
                </div>
            </div>
        </NodeViewWrapper>
    )
}
