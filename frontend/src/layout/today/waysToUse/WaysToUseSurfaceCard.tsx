import { ReactNode, useId } from 'react'

import { Text } from '@posthog/quill'

export interface WaysToUseSurfaceCardProps {
    logo: ReactNode
    title: string
    description: string
    illustration: ReactNode
    action: ReactNode
}

export function WaysToUseSurfaceCard({
    logo,
    title,
    description,
    illustration,
    action,
}: WaysToUseSurfaceCardProps): JSX.Element {
    const titleId = useId()

    return (
        <section aria-labelledby={titleId} className="flex min-w-0 flex-col gap-3">
            <div
                aria-hidden
                className="pointer-events-none relative h-36 overflow-hidden rounded-lg border border-border bg-chrome select-none"
                {...{ inert: '' }}
            >
                <span className="absolute top-3 left-3 flex size-6 items-center justify-center">{logo}</span>
                <div className="absolute inset-y-0 right-0 left-12 pt-3">{illustration}</div>
            </div>
            <div className="flex flex-col gap-1">
                <Text id={titleId} size="sm" weight="medium">
                    {title}
                </Text>
                <Text size="xs" variant="muted">
                    {description}
                </Text>
            </div>
            <div className="flex">{action}</div>
        </section>
    )
}
