import React, { Dispatch, SetStateAction } from 'react'
import { Select } from 'antd'
import { FundOutlined } from '@ant-design/icons'
import { smoothings } from 'lib/components/SmoothingFilter/smoothings'
import { ViewType } from '~/types'
import { intervalFilterLogic } from '../IntervalFilter/intervalFilterLogic'
import { useValues } from 'kea'

interface SmoothingFilterProps {
    view: ViewType
    disabled?: boolean
}

const useSmoothing = (): [string, Dispatch<SetStateAction<string>>] => {
    return React.useState<string>('1')
}

export function SmoothingFilter({ view, disabled }: SmoothingFilterProps): JSX.Element {
    const { interval } = useValues(intervalFilterLogic)
    const [smoothing, setSmoothing] = useSmoothing()
    const options = interval
        ? Object.entries(smoothings[interval]).map(([key, { label }]) => ({
              key,
              value: key,
              label:
                  key === smoothing ? (
                      <>
                          <FundOutlined /> {label}
                      </>
                  ) : (
                      label
                  ),
          }))
        : null

    console.log(options)
    return options && view === ViewType.TRENDS ? (
        <Select
            key={interval}
            bordered={false}
            disabled={disabled}
            defaultValue={'1'}
            value={smoothing || undefined}
            dropdownMatchSelectWidth={false}
            onChange={(key) => {
                setSmoothing(key)
            }}
            data-attr="smoothing-filter"
            options={options}
        />
    ) : (
        <></>
    )
}
