import React from 'react'
import { InfoCircleOutlined } from '@ant-design/icons'
import { Tooltip } from 'lib/components/Tooltip'

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
                <InfoCircleOutlined className="info-indicator" />
            </Tooltip>
        </h4>
    )
}
