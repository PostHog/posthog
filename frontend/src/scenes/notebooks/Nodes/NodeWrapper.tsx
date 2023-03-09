import { ReactNode } from 'react'
import { NodeViewWrapper } from '@tiptap/react'
import clsx from 'clsx'

export interface NodeWrapperProps {
    className: string
    children: ReactNode
}

export function NodeWrapper({ className, children }: NodeWrapperProps): JSX.Element {
    return (
        <NodeViewWrapper
            as="div"
            className={clsx(className, 'border bg-white p-2 mx-1 rounded-lg mb-2 overflow-y-auto')}
            data-drag-handle
        >
            {children}
        </NodeViewWrapper>
    )
}
