// import { useActions } from 'kea'
// import { trendsLogic } from 'scenes/trends/trendsLogic'
// import { EditorFilterProps } from '~/types'
import { Checkbox } from 'antd'
import { Tooltip } from 'lib/components/Tooltip'
import { InfoCircleOutlined } from '@ant-design/icons'
import { LifecycleQuery } from '~/queries/schema'
import '../../../scenes/insights/EditorFilters/LifecycleToggles.scss'
import { LifecycleToggle } from '~/types'

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

type LifecycleTogglesProps = {
    query: LifecycleQuery
    setQuery: (node: LifecycleQuery) => void
}

export function LifecycleToggles({ query, setQuery }: LifecycleTogglesProps): JSX.Element {
    // const { toggleLifecycle } = useActions(trendsLogic(insightProps))
    const toggleLifecycle = (name: LifecycleToggle): void => {
        if (query.lifecycleFilter?.toggledLifecycles?.includes(name)) {
            setQuery({
                ...query,
                lifecycleFilter: {
                    ...query.lifecycleFilter,
                    toggledLifecycles: query.lifecycleFilter.toggledLifecycles.filter((n) => n !== name),
                },
            })
        } else {
            setQuery({
                ...query,
                lifecycleFilter: {
                    ...query.lifecycleFilter,
                    toggledLifecycles: query.lifecycleFilter?.toggledLifecycles
                        ? [...query.lifecycleFilter.toggledLifecycles, name]
                        : [name],
                },
            })
        }
    }
    return (
        <>
            <div className="LifecycleToggles">
                {lifecycles.map((lifecycle, idx) => (
                    <div key={idx}>
                        {lifecycle.name}{' '}
                        <div>
                            <Checkbox
                                defaultChecked
                                className={lifecycle.name}
                                onChange={() => toggleLifecycle(lifecycle.name)}
                            />
                            <Tooltip title={lifecycle.tooltip}>
                                <InfoCircleOutlined className="info-indicator" />
                            </Tooltip>
                        </div>
                    </div>
                ))}
            </div>
        </>
    )
}
