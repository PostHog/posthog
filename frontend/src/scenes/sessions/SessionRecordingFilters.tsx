import React from 'react'
import { Input, Select } from 'antd'
import { RecordingDurationFilter } from 'scenes/sessions/sessionsTableLogic'
import { CloseButton } from 'lib/components/CloseButton'

interface Props {
    duration: RecordingDurationFilter | null
    onChange: (duration: RecordingDurationFilter | null) => void
}

export function SessionRecordingFilters({ duration, onChange }: Props): JSX.Element {
    const onOperatorChange = (value: '' | 'lt' | 'gt'): void => {
        if (value) {
            onChange([value, duration?.[1] || 0])
        } else {
            onChange(null)
        }
    }

    return (
        <div style={{ display: 'flex', alignItems: 'center' }}>
            <Select
                style={{ width: 212 }}
                defaultValue={duration ? duration[0] : undefined}
                value={duration ? duration[0] : undefined}
                onChange={onOperatorChange}
                placeholder="Filter by recording duration"
            >
                <Select.Option value="">Filter by recording duration</Select.Option>
                <Select.Option value="gt">Recording longer than</Select.Option>
                <Select.Option value="lt">Recording shorter than</Select.Option>
            </Select>
            {duration && (
                <>
                    <Input
                        style={{ width: 150, marginLeft: 8 }}
                        type="number"
                        value={duration[1] || undefined}
                        placeholder="0"
                        min={0}
                        addonAfter="sec"
                        step={1}
                        onChange={(event) => onChange([duration[0], parseFloat(event.target.value)])}
                    />
                    <CloseButton
                        onClick={() => onChange(null)}
                        style={{
                            float: 'none',
                            marginLeft: 4,
                        }}
                    />
                </>
            )}
        </div>
    )
}
