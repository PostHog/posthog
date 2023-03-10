import { ReactNode } from 'react'
import { NodeViewWrapper } from '@tiptap/react'
import clsx from 'clsx'
import { IconDragHandle } from 'lib/lemon-ui/icons'

export interface NodeWrapperProps {
    title: string
    className: string
    children: ReactNode
}

export function NodeWrapper({ title, className, children }: NodeWrapperProps): JSX.Element {
    return (
        <NodeViewWrapper as="div" className={clsx(className, 'flex flex-col gap-1 overflow-hidden')}>
            <div className="flex items-center text-xs text-muted-alt truncate" data-drag-handle>
                <IconDragHandle className="text-muted-alt cursor-move text-base shrink-0" />
                {title}
            </div>
            <div className={clsx('border bg-white rounded-lg mb-2 overflow-y-auto flex-1')}>{children}</div>
        </NodeViewWrapper>
    )
}
