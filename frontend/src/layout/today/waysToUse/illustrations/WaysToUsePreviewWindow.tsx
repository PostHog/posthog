import { ReactNode } from 'react'

import { Text } from '@posthog/quill'

export interface WaysToUsePreviewWindowProps {
    title: string
    children: ReactNode
}

export function WaysToUsePreviewWindow({ title, children }: WaysToUsePreviewWindowProps): JSX.Element {
    return (
        <div className="absolute top-4 -right-6 -bottom-6 left-14 overflow-hidden rounded-lg border border-border bg-background shadow-sm transition-transform duration-300 ease-out group-has-[a:hover]/card:-translate-y-0.5 group-has-[a:focus-visible]/card:-translate-y-0.5 motion-reduce:transition-none">
            <div className="mr-6">
                <div className="flex items-center gap-1 border-b border-border px-3 py-1.5">
                    <span className="size-1.5 rounded-full bg-border" />
                    <span className="size-1.5 rounded-full bg-border" />
                    <span className="size-1.5 rounded-full bg-border" />
                    <Text size="xxs" variant="muted" className="ml-1.5 truncate">
                        {title}
                    </Text>
                </div>
                {children}
            </div>
        </div>
    )
}
