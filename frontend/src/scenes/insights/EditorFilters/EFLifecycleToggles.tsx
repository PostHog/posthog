import React from 'react'
import { useActions } from 'kea'
import { trendsLogic } from 'scenes/trends/trendsLogic'
import { EditorFilterProps } from '~/types'
import { Checkbox } from 'antd'
import { Tooltip } from 'lib/components/Tooltip'
import { InfoCircleOutlined } from '@ant-design/icons'
import './EFLifecycleToggles.scss'

const lifecycles = [
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

export function EFLifecycleToggles({ insightProps }: EditorFilterProps): JSX.Element {
    const { toggleLifecycle } = useActions(trendsLogic(insightProps))
    return (
        <>
            <div className="EFLifecycleToggles">
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
