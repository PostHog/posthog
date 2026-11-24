import { Text } from '@posthog/quill'

import { WarehouseSection } from '../WarehouseConsole/WarehouseSection'

const STEPS = [
    'You choose a warehouse name and a schema name for this project. The name becomes part of your connection host and catalog.',
    'A managed warehouse is created for your organization. Every project in your organization shares it.',
    'The password for the root login is shown once when setup finishes. Connection details are on the Connect page.',
    'Your events and persons are copied in. The PostHog data page shows how far that has got.',
    'Tables from your sources land after their next sync.',
    'Other projects in your organization join later by choosing their own schema name.',
]

export function WarehouseExplainerSetup(): JSX.Element {
    return (
        <WarehouseSection title="What happens when you set it up" data-attr="warehouse-explainer-setup">
            <ol className="m-0 flex max-w-2xl list-decimal flex-col gap-1.5 pl-5">
                {STEPS.map((step) => (
                    <li key={step}>
                        <Text size="sm" render={<span />}>
                            {step}
                        </Text>
                    </li>
                ))}
            </ol>
        </WarehouseSection>
    )
}
