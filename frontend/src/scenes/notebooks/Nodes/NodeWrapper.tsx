import { ReactNode } from 'react'
import { NodeViewWrapper } from '@tiptap/react'
import clsx from 'clsx'
import { IconDragHandle, IconLink } from 'lib/lemon-ui/icons'
import { LemonButton } from '@posthog/lemon-ui'

export interface NodeWrapperProps {
    className: string
    children: ReactNode
}

export function NodeWrapper({ className, children }: NodeWrapperProps): JSX.Element {
    return (
        <NodeViewWrapper as="div" className={clsx(className, 'flex items-start gap-1')}>
            <div className="flex flex-col gap-2">
                <LemonButton size="small" noPadding icon={<IconDragHandle />} status="primary-alt" data-drag-handle />

                <LemonButton size="small" noPadding icon={<IconLink />} status="primary-alt" />
            </div>

            <div className={clsx('border bg-white rounded-lg mb-2 overflow-y-auto flex-1')}>{children}</div>
        </NodeViewWrapper>
    )
}
