import { ReactNode, useState } from 'react'
import { NodeViewWrapper } from '@tiptap/react'
import clsx from 'clsx'
import { IconDragHandle } from 'lib/lemon-ui/icons'

export interface NodeWrapperProps {
    title: string
    className: string
    children: ReactNode
    preview?: ReactNode // Minified preview mode to show in small screen situations and unexpanded modes. If not defined, children are mounted and rendered.
}

export function NodeWrapper({ title, className, children, preview }: NodeWrapperProps): JSX.Element {
    const [isEdit, setIsEdit] = useState<boolean>(false)
    const [isPreview, setIsPreview] = useState<boolean>(true)

    const previewNode = preview ?? children // default to children if no preview

    return (
        <NodeViewWrapper as="div" className={clsx(className, 'flex flex-col gap-1 overflow-hidden')}>
            <div className="flex items-center justify-between text-xs text-muted-alt truncate" data-drag-handle>
                <div className="shrink-0">
                    <IconDragHandle className="text-muted-alt cursor-move text-base shrink-0" />
                    <span>{title}</span>
                </div>
                <div className="shrink-0 flex gap-4">
                    <span
                        className="cursor-pointer"
                        onClick={() => {
                            setIsEdit(!isEdit)
                        }}
                    >
                        {isEdit ? 'Done' : 'Edit'}
                    </span>
                    {!!preview && (
                        <span
                            className="cursor-pointer"
                            onClick={() => {
                                setIsPreview(!isPreview)
                            }}
                        >
                            {isPreview ? 'Full' : 'Preview'}
                        </span>
                    )}
                </div>
            </div>
            <div className={clsx('border bg-white rounded-lg mb-2 overflow-y-auto flex-1')}>
                {isPreview ? previewNode : children}
            </div>
        </NodeViewWrapper>
    )
}
