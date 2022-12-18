import { LifecycleQuery } from '~/queries/schema'
import { LifecycleToggle } from '~/types'
import { LemonCheckbox, LemonLabel } from '@posthog/lemon-ui'

const lifecycles: { name: LifecycleToggle; tooltip: string; color: string }[] = [
    {
        name: 'new',
        tooltip: 'Users who were first seen on this period and did the activity during the period.',
        color: 'var(--lifecycle-new)',
    },
    {
        name: 'returning',
        tooltip: 'Users who did activity both this and previous period.',
        color: 'var(--lifecycle-returning)',
    },
    {
        name: 'resurrecting',
        tooltip:
            'Users who did the activity this period but did not do the activity on the previous period (i.e. were inactive for 1 or more periods).',
        color: 'var(--lifecycle-resurrecting)',
    },
    {
        name: 'dormant',
        tooltip:
            'Users who went dormant on this period, i.e. users who did not do the activity this period but did the activity on the previous period.',
        color: 'var(--lifecycle-dormant)',
    },
]

type LifecycleTogglesProps = {
    query: LifecycleQuery
    setQuery: (node: LifecycleQuery) => void
}

const DEFAULT_LIFECYCLE_TOGGLES: LifecycleToggle[] = ['new', 'returning', 'resurrecting', 'dormant']

export function LifecycleToggles({ query, setQuery }: LifecycleTogglesProps): JSX.Element {
    const toggledLifecycles = query.lifecycleFilter?.toggledLifecycles || DEFAULT_LIFECYCLE_TOGGLES
    const setToggledLifecycles = (lifecycles: LifecycleToggle[]): void => {
        setQuery({
            ...query,
            lifecycleFilter: {
                ...query.lifecycleFilter,
                toggledLifecycles: lifecycles,
            },
        })
    }

    const toggleLifecycle = (name: LifecycleToggle): void => {
        if (toggledLifecycles.includes(name)) {
            setToggledLifecycles(toggledLifecycles.filter((n) => n !== name))
        } else {
            setToggledLifecycles([...toggledLifecycles, name])
        }
    }

    return (
        <div className="flex flex-col -mt-1">
            {lifecycles.map((lifecycle) => (
                <LemonLabel key={lifecycle.name} info={lifecycle.tooltip}>
                    <LemonCheckbox
                        label={lifecycle.name.charAt(0).toUpperCase() + lifecycle.name.substring(1)}
                        color={lifecycle.color}
                        checked={toggledLifecycles.includes(lifecycle.name)}
                        onChange={() => toggleLifecycle(lifecycle.name)}
                    />
                </LemonLabel>
            ))}
        </div>
    )
}
