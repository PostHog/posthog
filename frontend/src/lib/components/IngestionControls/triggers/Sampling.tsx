import { useValues } from 'kea'
import { useState } from 'react'

import { LemonButton, LemonInput, lemonToast } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'

import { AccessControlLevel } from '~/types'

import { ingestionControlsLogic } from '../ingestionControlsLogic'

export function SamplingTrigger({
    initialSampleRate,
    onChange,
}: {
    initialSampleRate: number
    onChange: (value: number) => void
}): JSX.Element {
    const { resourceType } = useValues(ingestionControlsLogic)

    const [value, setValue] = useState<number | undefined>(initialSampleRate)

    const updateSampling = (): void => {
        const returnRate = typeof value == 'number' ? value / 100 : 0
        if (returnRate > 1) {
            lemonToast.error('Session recording sample rate must be between 0 to 100')
        } else {
            onChange(returnRate)
        }
    }

    return (
        <AccessControlAction resourceType={resourceType} minAccessLevel={AccessControlLevel.Editor}>
            <div className="flex flex-row gap-x-2">
                <LemonInput
                    type="number"
                    className="[&>input::-webkit-inner-spin-button]:appearance-none"
                    onChange={(value) => setValue(value)}
                    min={0}
                    max={100}
                    suffix={<>%</>}
                    value={value}
                    onPressEnter={updateSampling}
                    data-attr="sampling-setting-input"
                />
                <LemonButton
                    type="primary"
                    disabledReason={initialSampleRate === value && 'there was no change in sample rate'}
                    onClick={updateSampling}
                    data-attr="sampling-setting-update"
                >
                    Update
                </LemonButton>
            </div>
        </AccessControlAction>
    )
}
