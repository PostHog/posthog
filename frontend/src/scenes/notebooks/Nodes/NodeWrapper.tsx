import { NodeViewProps, NodeViewWrapper } from '@tiptap/react'
import { ReactNode, useState } from 'react'
import clsx from 'clsx'
import { IconDragHandle, IconLink } from 'lib/lemon-ui/icons'
import { Link } from '@posthog/lemon-ui'

export interface NodeWrapperProps extends NodeViewProps {
    title: string
    className: string
    children: ReactNode | ((isEdit: boolean, isPreview: boolean) => ReactNode)
    preview?: ReactNode // Minified preview mode to show in small screen situations and unexpanded modes. If not defined, children are mounted and rendered.
    edit?: ReactNode // TODO: This will be replaced with a separate query sidebar outside of the context of a notebook
    href?: string
}

export function NodeWrapper({
    title,
    className,
    children,
    preview,
    selected,
    edit,
    href,
}: NodeWrapperProps): JSX.Element {
    const [isEdit, setIsEdit] = useState<boolean>(false)

    const content = selected ? children : preview ?? children

    return (
        <NodeViewWrapper as="div" className={clsx(className, 'flex flex-col gap-1 overflow-hidden')}>
            <div className="flex items-center justify-between text-xs text-muted-alt truncate" data-drag-handle>
                <div className="shrink-0">
                    <IconDragHandle className="text-muted-alt cursor-move text-base shrink-0" />
                    <span>{title}</span>
                </div>
                <div className="shrink-0 flex gap-4">
                    {!!edit && (
                        <span
                            className="cursor-pointer"
                            onClick={() => {
                                setIsEdit(!isEdit)
                            }}
                        >
                            {isEdit ? 'Done' : 'Edit'}
                        </span>
                    )}

                    {href && (
                        <Link to={href}>
                            <IconLink /> Link
                        </Link>
                    )}
                </div>
            </div>
            <div className="flex flex-row gap-4">
                {!!edit && isEdit && (
                    <div
                        className={clsx('relative border bg-white rounded-lg mb-2 overflow-y-auto flex-1 max-w-60', {
                            'border-primary border-2': selected,
                        })}
                    >
                        {edit}
                    </div>
                )}
                <div
                    className={clsx('relative border bg-white rounded-lg mb-2 overflow-y-auto flex-1', {
                        'border-primary border-2': selected,
                    })}
                >
                    {content}
                </div>
            </div>
        </NodeViewWrapper>
    )
}
