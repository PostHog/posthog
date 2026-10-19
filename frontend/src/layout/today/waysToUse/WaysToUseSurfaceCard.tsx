import { ReactNode, useId } from 'react'

import { Heading, Text } from '@posthog/quill'

export interface WaysToUseSurfaceCardProps {
    logo: ReactNode
    title: string
    description: string
    illustration: ReactNode
    action: ReactNode
    status?: ReactNode
}

export function WaysToUseSurfaceCard({
    logo,
    title,
    description,
    illustration,
    action,
    status,
}: WaysToUseSurfaceCardProps): JSX.Element {
    const titleId = useId()

    return (
        <section
            aria-labelledby={titleId}
            className="group/card relative row-span-3 grid min-w-0 grid-rows-subgrid gap-y-3 @md:@max-3xl:row-span-1 @md:@max-3xl:grid-cols-2 @md:@max-3xl:grid-rows-none @md:@max-3xl:content-start @md:@max-3xl:gap-x-4 transition duration-300 ease-out group-data-[starting-style]/popup:translate-y-2 group-data-[starting-style]/popup:opacity-0 nth-2:delay-60 nth-3:delay-120 motion-reduce:transition-none"
        >
            <div
                className="relative h-48 overflow-hidden rounded-xl border border-border bg-fill-hover @md:@max-3xl:row-span-2"
                {...{ inert: '' }}
            >
                <span className="absolute top-4 left-4 flex size-6 items-center justify-center">{logo}</span>
                {illustration}
            </div>
            <div className="flex flex-col gap-1 @md:@max-3xl:col-start-2 @md:@max-3xl:self-end">
                <div className="flex items-center gap-2">
                    <Heading id={titleId} size="sm" render={<h3 />} className="m-0">
                        {title}
                    </Heading>
                    {status}
                </div>
                <Text size="xs" variant="muted" className="text-pretty">
                    {description}
                </Text>
            </div>
            <div className="flex items-center @md:@max-3xl:col-start-2 @md:@max-3xl:self-start">{action}</div>
        </section>
    )
}
