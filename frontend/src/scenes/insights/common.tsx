import React from 'react'
import { InfoCircleOutlined } from '@ant-design/icons'
import { Tooltip } from 'antd'

export function GlobalFiltersTitle({ unit = 'series' }: { unit?: string }): JSX.Element {
    return (
        <h4 className="secondary">
            Filters{' '}
            <Tooltip
                title={
                    <>
                        These filters will apply to <b>all</b> the {unit} in this graph.
                    </>
                }
            >
                <InfoCircleOutlined />
            </Tooltip>
        </h4>
    )
}
