import { ReactNode } from 'react'
import { NodeViewWrapper } from '@tiptap/react'
import clsx from 'clsx'

export interface NodeWrapperProps {
    className: string
    children: ReactNode
}

export function NodeWrapper({ className, children }: NodeWrapperProps): JSX.Element {
    return (
        <NodeViewWrapper className={clsx(className, 'border bg-white p-2 rounded-lg')} data-drag-handle>
            {children}
        </NodeViewWrapper>
    )
}
