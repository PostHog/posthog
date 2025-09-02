import { useActions, useValues } from 'kea'

import { LemonCheckbox, LemonLabel } from '@posthog/lemon-ui'

import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { LifecycleFilter } from '~/queries/schema/schema-general'
import { EditorFilterProps, LifecycleToggle } from '~/types'

// Tooltip explanations taken from https://posthog.com/docs/product-analytics/lifecycle#interpreting-your-lifecycle
const lifecycles: { name: LifecycleToggle; tooltip: string; color: string }[] = [
    {
        name: 'new',
        tooltip:
            'Users who did the event or action during the interval and were also created during that period – e.g. created an account and sent a message today.',
        color: 'var(--color-lifecycle-new)',
    },
    {
        name: 'returning',
        tooltip:
            'Someone who was active in the previous interval and is also active in the current interval – e.g. sent a message yesterday and also sent a message today.',
        color: 'var(--color-lifecycle-returning)',
    },
    {
        name: 'resurrecting',
        tooltip:
            'Someone who was not active in the previous interval but became active once again – e.g. did not send any messages for 10 days, but sent one today.',
        color: 'var(--color-lifecycle-resurrecting)',
    },
    {
        name: 'dormant',
        tooltip:
            'Users who are not active in the current interval, but were active in the previous interval – e.g. someone who has not sent a message today, but sent one yesterday.',
        color: 'var(--color-lifecycle-dormant)',
    },
]

const DEFAULT_LIFECYCLE_TOGGLES: LifecycleToggle[] = ['new', 'returning', 'resurrecting', 'dormant']

export function LifecycleToggles({ insightProps }: EditorFilterProps): JSX.Element {
    const { insightFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    const toggledLifecycles = (insightFilter as LifecycleFilter)?.toggledLifecycles || DEFAULT_LIFECYCLE_TOGGLES
    const toggleLifecycle = (name: LifecycleToggle): void => {
        if (toggledLifecycles.includes(name)) {
            updateInsightFilter({ toggledLifecycles: toggledLifecycles.filter((n) => n !== name) })
        } else {
            updateInsightFilter({ toggledLifecycles: [...toggledLifecycles, name] })
        }
    }

    return (
        <div className="flex flex-col -mt-1 uppercase">
            {lifecycles.map((lifecycle) => (
                <LemonLabel key={lifecycle.name} info={lifecycle.tooltip}>
                    <LemonCheckbox
                        label={lifecycle.name}
                        color={lifecycle.color}
                        checked={toggledLifecycles.includes(lifecycle.name)}
                        onChange={() => toggleLifecycle(lifecycle.name)}
                    />
                </LemonLabel>
            ))}
        </div>
    )
}
