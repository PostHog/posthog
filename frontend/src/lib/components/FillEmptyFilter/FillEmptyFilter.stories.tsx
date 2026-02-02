import { Meta, StoryFn } from '@storybook/react'
import { useState } from 'react'

import { LemonCheckbox } from '@posthog/lemon-ui'

const meta: Meta = {
    title: 'Filters/Fill Empty Filter',
    tags: ['autodocs'],
}
export default meta

export const Default: StoryFn = () => {
    const [fillEmpty, setFillEmpty] = useState(false)

    return (
        <div className="space-y-4">
            <div>
                <h3 className="mb-2">Fill Empty Filter</h3>
                <p className="text-muted mb-4">
                    When enabled, empty data points (zeros) in trends charts will be filled with the previous non-zero
                    value. This is useful when you have gaps in your data due to missing events.
                </p>
            </div>
            <LemonCheckbox
                className="p-1 px-2"
                onChange={() => setFillEmpty(!fillEmpty)}
                checked={fillEmpty}
                label={<span className="font-normal">Fill gaps with previous value</span>}
                size="small"
            />
            <div className="mt-4 p-4 bg-bg-light rounded border">
                <strong>Current state:</strong> {fillEmpty ? 'Enabled' : 'Disabled'}
                <div className="mt-2 text-sm text-muted">
                    {fillEmpty
                        ? 'Data gaps will be filled with the last non-zero value'
                        : 'Data gaps will show as zeros'}
                </div>
            </div>
        </div>
    )
}

export const Checked: StoryFn = () => {
    return (
        <LemonCheckbox
            className="p-1 px-2"
            onChange={() => {}}
            checked={true}
            label={<span className="font-normal">Fill gaps with previous value</span>}
            size="small"
        />
    )
}

export const Unchecked: StoryFn = () => {
    return (
        <LemonCheckbox
            className="p-1 px-2"
            onChange={() => {}}
            checked={false}
            label={<span className="font-normal">Fill gaps with previous value</span>}
            size="small"
        />
    )
}
