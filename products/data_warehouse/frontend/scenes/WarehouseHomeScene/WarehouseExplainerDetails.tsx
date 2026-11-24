import { IconLock, IconPieChart, IconPulse } from '@posthog/icons'
import { Text } from '@posthog/quill'

import { WarehouseSection } from '../WarehouseConsole/WarehouseSection'

const SETUP_STEPS = [
    'Name your warehouse',
    "This project's events and persons copy in",
    'Source tables land on their next sync',
    'Enable your other projects one by one',
]

const INCLUDED = [
    { icon: <IconPulse />, label: 'See what has landed' },
    { icon: <IconPieChart />, label: 'Usage, queries and storage' },
    { icon: <IconLock />, label: 'Logins for your tools' },
]

/** Two short lists under the hero: what setup does, and the pages that come with a warehouse. */
export function WarehouseExplainerDetails(): JSX.Element {
    return (
        <div className="grid gap-4 @2xl/warehouse-home:grid-cols-2">
            <WarehouseSection title="When you set it up" data-attr="warehouse-explainer-setup">
                <ol className="m-0 flex list-none flex-col gap-2 p-0">
                    {SETUP_STEPS.map((step, index) => (
                        <li key={step} className="flex items-center gap-2.5">
                            <span
                                className="flex size-5 shrink-0 items-center justify-center rounded-full border text-xs tabular-nums text-muted-foreground"
                                aria-hidden
                            >
                                {index + 1}
                            </span>
                            <Text size="sm" render={<span />}>
                                {step}
                            </Text>
                        </li>
                    ))}
                </ol>
            </WarehouseSection>
            <WarehouseSection title="Also included" data-attr="warehouse-explainer-features">
                <ul className="m-0 flex list-none flex-col gap-2 p-0">
                    {INCLUDED.map((item) => (
                        <li key={item.label} className="flex items-center gap-2.5">
                            <span
                                className="flex size-5 shrink-0 items-center justify-center text-muted-foreground [&_svg]:size-4"
                                aria-hidden
                            >
                                {item.icon}
                            </span>
                            <Text size="sm" render={<span />}>
                                {item.label}
                            </Text>
                        </li>
                    ))}
                </ul>
            </WarehouseSection>
        </div>
    )
}
