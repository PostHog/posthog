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
            onChange([value, duration?.[1] || 0, duration?.[2] || 'm'])
        } else {
            onChange(null)
        }
    }

    return (
        <div style={{ display: 'flex', alignItems: 'center' }}>
            <Select
                defaultValue={duration ? duration[0] : undefined}
                value={duration ? duration[0] : undefined}
                onChange={onOperatorChange}
                placeholder="Filter by recording duration"
            >
                <Select.Option value="gt">Recording longer than</Select.Option>
                <Select.Option value="lt">Recording shorter than</Select.Option>
            </Select>
            {duration && (
                <>
                    <Input
                        style={{ width: 200, marginLeft: 8 }}
                        type="number"
                        value={duration[1] || undefined}
                        placeholder="0"
                        min={0}
                        addonAfter={
                            <Select
                                showSearch={false}
                                value={duration[2]}
                                onChange={(value) => onChange([duration[0], duration[1], value])}
                            >
                                <Select.Option value="s">seconds</Select.Option>
                                <Select.Option value="m">minutes</Select.Option>
                                <Select.Option value="h">hours</Select.Option>
                            </Select>
                        }
                        step={1}
                        onChange={(event) => onChange([duration[0], parseFloat(event.target.value), duration[2]])}
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
