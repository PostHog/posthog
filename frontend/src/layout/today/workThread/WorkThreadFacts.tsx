import { Text } from '@posthog/quill'

import type { WorkFactApi } from 'products/today/frontend/generated/api.schemas'

export function WorkThreadFacts({ facts }: { facts: WorkFactApi[] }): JSX.Element {
    return (
        <dl className="m-0 flex flex-col gap-1">
            {facts.map((fact) => (
                <div key={fact.label} className="flex flex-wrap gap-x-3">
                    <dt className="w-28 shrink-0">
                        <Text size="xs" variant="muted" render={<span className="m-0" />}>
                            {fact.label}
                        </Text>
                    </dt>
                    <dd className="m-0 min-w-0 flex-1 basis-40">
                        <Text size="xs" render={<span className="m-0 break-words" />}>
                            {fact.value}
                        </Text>
                    </dd>
                </div>
            ))}
        </dl>
    )
}
