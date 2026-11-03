import type { ReactNode } from 'react'

import { Heading } from '@posthog/quill'

export function QuillMetricDefinitionSection({ children }: { children: ReactNode }): JSX.Element {
    return (
        <section className="flex flex-col gap-2">
            <Heading size="sm" render={<h3 className="m-0" />}>
                Definition
            </Heading>
            {children}
        </section>
    )
}
