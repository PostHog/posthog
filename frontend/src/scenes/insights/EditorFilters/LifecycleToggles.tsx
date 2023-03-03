import { useActions, useValues } from 'kea'
import { trendsLogic } from 'scenes/trends/trendsLogic'
import { EditorFilterProps, LifecycleToggle } from '~/types'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import './LifecycleToggles.scss'
import { LemonCheckbox } from 'lib/lemon-ui/LemonCheckbox'
import { IconInfo } from 'lib/lemon-ui/icons'

const lifecycles: { name: LifecycleToggle; tooltip: string }[] = [
    { name: 'new', tooltip: 'Users who were first seen on this period and did the activity during the period.' },
    { name: 'returning', tooltip: 'Users who did activity both this and previous period.' },
    {
        name: 'resurrecting',
        tooltip:
            'Users who did the activity this period but did not do the activity on the previous period (i.e. were inactive for 1 or more periods).',
    },
    {
        name: 'dormant',
        tooltip:
            'Users who went dormant on this period, i.e. users who did not do the activity this period but did the activity on the previous period.',
    },
]

export function LifecycleToggles({ insightProps }: EditorFilterProps): JSX.Element {
    const { toggledLifecycles } = useValues(trendsLogic(insightProps))
    const { toggleLifecycle } = useActions(trendsLogic(insightProps))

    console.log('toggles: toggledLifecycles', toggledLifecycles)
    return (
        <>
            <div className="LifecycleToggles">
                {lifecycles.map((lifecycle, idx) => {
                    console.log('toggles: lifecycle.name', lifecycle.name)
                    console.log('toggles: is checked', toggledLifecycles.includes(lifecycle.name))
                    return (
                        <div key={idx}>
                            {lifecycle.name}{' '}
                            <div>
                                <LemonCheckbox
                                    checked={toggledLifecycles.includes(lifecycle.name)}
                                    className={lifecycle.name}
                                    onChange={() => toggleLifecycle(lifecycle.name)}
                                />
                                <Tooltip title={lifecycle.tooltip}>
                                    <IconInfo className="info-indicator" />
                                </Tooltip>
                            </div>
                        </div>
                    )
                })}
            </div>
        </>
    )
}
