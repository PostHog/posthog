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
        <NodeViewWrapper
            as="div"
            className={clsx(className, 'NotebookNode flex flex-col gap-1 overflow-hidden', {
                'NotebookNode--selected': selected,
            })}
        >
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
            <div className="flex flex-row gap-4 relative z-10">
                <div
                    // className={clsx('relative mb-2 flex-1 overflow-y-auto')}
                    className={clsx('relative mb-2 overflow-y-auto flex-1')}
                >
                    {content}
                </div>
            </div>
        </NodeViewWrapper>
    )
}
