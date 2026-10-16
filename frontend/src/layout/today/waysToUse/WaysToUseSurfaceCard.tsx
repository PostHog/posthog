import { ReactNode, useId } from 'react'

import { Heading, Text } from '@posthog/quill'

const ENTER_DELAYS = ['delay-0', 'delay-60', 'delay-120', 'delay-180']

export interface WaysToUseSurfaceCardProps {
    order: number
    logo: ReactNode
    title: string
    description: string
    illustration: ReactNode
    action: ReactNode
}

export function WaysToUseSurfaceCard({
    order,
    logo,
    title,
    description,
    illustration,
    action,
}: WaysToUseSurfaceCardProps): JSX.Element {
    const titleId = useId()

    return (
        <section
            aria-labelledby={titleId}
            className={`group/card relative row-span-3 grid min-w-0 grid-rows-subgrid gap-y-3 transition duration-300 ease-out group-data-[starting-style]/popup:translate-y-2 group-data-[starting-style]/popup:opacity-0 motion-reduce:transition-none ${ENTER_DELAYS[order]}`}
        >
            <div
                aria-hidden
                className="pointer-events-none relative h-36 overflow-hidden rounded-lg border border-border bg-chrome select-none"
                {...{ inert: '' }}
            >
                <span className="absolute top-3 left-3 flex size-6 items-center justify-center">{logo}</span>
                <div className="absolute top-0 right-0 -bottom-2 left-12 pt-3 transition-transform duration-200 ease-out group-has-[a:hover]/card:-translate-y-1 group-has-[a:focus-visible]/card:-translate-y-1 motion-reduce:transition-none">
                    {illustration}
                </div>
            </div>
            <div className="flex flex-col gap-1">
                <Heading id={titleId} size="sm" render={<h3 />} className="m-0">
                    {title}
                </Heading>
                <Text size="xs" variant="muted" className="text-pretty">
                    {description}
                </Text>
            </div>
            <div className="flex items-center">{action}</div>
        </section>
    )
}
