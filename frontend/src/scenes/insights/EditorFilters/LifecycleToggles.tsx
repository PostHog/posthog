import { useActions, useValues } from 'kea'
import { trendsLogic } from 'scenes/trends/trendsLogic'
import { EditorFilterProps, LifecycleToggle } from '~/types'
import { LemonCheckbox } from 'lib/lemon-ui/LemonCheckbox'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel/LemonLabel'

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

export function LifecycleToggles({ insightProps }: EditorFilterProps): JSX.Element {
    const { toggledLifecycles } = useValues(trendsLogic(insightProps))
    const { toggleLifecycle } = useActions(trendsLogic(insightProps))

    return (
        <>
            <div className="flex flex-col -mt-1 uppercase">
                {lifecycles.map((lifecycle) => (
                    <LemonLabel key={lifecycle.name} info={lifecycle.tooltip}>
                        <LemonCheckbox
                            className={'uppercase'}
                            label={lifecycle.name}
                            color={lifecycle.color}
                            checked={toggledLifecycles.includes(lifecycle.name)}
                            onChange={() => toggleLifecycle(lifecycle.name)}
                        />
                    </LemonLabel>
                ))}
            </div>
        </>
    )
}
