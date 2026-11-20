import { ReactNode } from 'react'

import { Heading, Text } from '@posthog/quill'

export function QuillAccessDetailSection({
    title,
    description,
    children,
}: {
    title: string
    description?: string
    children: ReactNode
}): JSX.Element {
    return (
        <section className="flex flex-col gap-2">
            <div className="flex flex-col gap-1">
                <Heading size="sm" render={<h3 className="m-0" />}>
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
