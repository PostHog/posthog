import { ReactNode } from 'react'

import { DialogBody, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@posthog/quill'

import { AlertEditorActionsProps } from './AlertEditor'
import { QuillAlertEditorActions } from './QuillAlertEditorActions'

export interface QuillAlertEditorProps extends AlertEditorActionsProps {
    title: string
    description?: string
    children: ReactNode
}

/** Header, scrolling body and action footer of an alert editor. Render it inside a quill `DialogContent`. */
export function QuillAlertEditor({
    title,
    description,
    children,
    ...actionsProps
}: QuillAlertEditorProps): JSX.Element {
    return (
        <>
            <DialogHeader>
                <DialogTitle>{title}</DialogTitle>
                {description ? <DialogDescription>{description}</DialogDescription> : null}
            </DialogHeader>
            <DialogBody>{children}</DialogBody>
            <DialogFooter className="flex-wrap items-center">
                <QuillAlertEditorActions {...actionsProps} />
            </DialogFooter>
        </>
    )
}
