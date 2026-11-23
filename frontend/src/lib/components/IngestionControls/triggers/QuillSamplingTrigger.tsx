import { useState } from 'react'

import { Button, InputGroup, InputGroupAddon, InputGroupInput, InputGroupText } from '@posthog/quill'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'

import { submitSampleRate } from './Sampling'

export function QuillSamplingTrigger({
    initialSampleRate,
    onChange,
}: {
    initialSampleRate: number
    onChange: (value: number) => void
}): JSX.Element {
    const [value, setValue] = useState<number | undefined>(initialSampleRate)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    const updateSampling = (): void => submitSampleRate(value, onChange)

    return (
        <div className="flex flex-wrap items-center gap-2">
            <InputGroup className="w-24">
                <InputGroupInput
                    type="number"
                    aria-label="Sample rate"
                    min={0}
                    max={100}
                    value={value ?? ''}
                    onChange={(event) => setValue(event.target.value === '' ? undefined : Number(event.target.value))}
                    onKeyDown={(event) => {
                        if (event.key === 'Enter' && !restrictedReason) {
                            updateSampling()
                        }
                    }}
                    data-attr="sampling-setting-input"
                    disabledReason={restrictedReason}
                />
                <InputGroupAddon align="inline-end">
                    <InputGroupText>%</InputGroupText>
                </InputGroupAddon>
            </InputGroup>
            <Button
                variant="primary"
                disabledReason={
                    initialSampleRate === value ? 'Update the sample rate to save changes' : restrictedReason
                }
                onClick={updateSampling}
                data-attr="sampling-setting-update"
            >
                Update
            </Button>
        </div>
    )
}
