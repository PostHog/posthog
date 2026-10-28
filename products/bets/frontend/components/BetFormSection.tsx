import type { ReactNode } from 'react'

import { Heading, Text } from '@posthog/quill'

export function BetFormSection({
    id,
    title,
    description,
    children,
}: {
    id: string
    title: string
    description?: string
    children: ReactNode
}): JSX.Element {
    return (
        <section aria-labelledby={id} className="Bets__formSection flex flex-col gap-4">
            <div className="flex flex-col gap-1">
                <Heading id={id} size="base" render={<h2 className="m-0" />}>
                    {title}
                </Heading>
                {description && (
                    <Text size="xs" variant="muted" render={<p className="m-0" />}>
                        {description}
                    </Text>
                )}
            </div>
            {children}
        </section>
    )
}
