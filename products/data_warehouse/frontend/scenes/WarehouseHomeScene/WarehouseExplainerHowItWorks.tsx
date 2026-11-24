import { Text } from '@posthog/quill'

import { WarehouseSection } from '../WarehouseConsole/WarehouseSection'

const STEPS = [
    { title: 'Your PostHog data', body: 'Your events and persons are copied in.' },
    { title: 'Your sources', body: 'Tables from your sources land after each sync.' },
    { title: 'Your queries', body: 'Query it all with SQL in PostHog or from your own tools.' },
]

export function WarehouseExplainerHowItWorks(): JSX.Element {
    return (
        <WarehouseSection title="How it works" data-attr="warehouse-explainer-how-it-works">
            <ol className="m-0 grid list-none gap-3 p-0 @2xl/warehouse-home:grid-cols-3">
                {STEPS.map((step, index) => (
                    <li key={step.title} className="flex min-w-0 flex-col gap-0.5">
                        <Text size="xs" variant="muted" className="tabular-nums" render={<span />}>
                            Step {index + 1}
                        </Text>
                        <Text size="sm" weight="semibold" render={<span />}>
                            {step.title}
                        </Text>
                        <Text size="xs" variant="muted" render={<span />}>
                            {step.body}
                        </Text>
                    </li>
                ))}
            </ol>
        </WarehouseSection>
    )
}
