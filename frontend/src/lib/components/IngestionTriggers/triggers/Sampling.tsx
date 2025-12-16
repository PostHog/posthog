import { useValues } from 'kea'

import { LemonSelect } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'

import { AccessControlLevel } from '~/types'

import { ingestionTriggersLogic } from '../ingestionTriggersLogic'

export function SamplingTrigger({
    value,
    onChange,
}: {
    value: string
    onChange: (value: string) => void
}): JSX.Element {
    const { resourceType } = useValues(ingestionTriggersLogic)

    return (
        <AccessControlAction resourceType={resourceType} minAccessLevel={AccessControlLevel.Editor}>
            <LemonSelect
                onChange={onChange}
                dropdownMatchSelectWidth={false}
                options={[
                    {
                        label: '100% (no sampling)',
                        value: '1.00',
                    },
                    {
                        label: '95%',
                        value: '0.95',
                    },
                    {
                        label: '90%',
                        value: '0.90',
                    },
                    {
                        label: '85%',
                        value: '0.85',
                    },
                    {
                        label: '80%',
                        value: '0.80',
                    },
                    {
                        label: '75%',
                        value: '0.75',
                    },
                    {
                        label: '70%',
                        value: '0.70',
                    },
                    {
                        label: '65%',
                        value: '0.65',
                    },
                    {
                        label: '60%',
                        value: '0.60',
                    },
                    {
                        label: '55%',
                        value: '0.55',
                    },
                    {
                        label: '50%',
                        value: '0.50',
                    },
                    {
                        label: '45%',
                        value: '0.45',
                    },
                    {
                        label: '40%',
                        value: '0.40',
                    },
                    {
                        label: '35%',
                        value: '0.35',
                    },
                    {
                        label: '30%',
                        value: '0.30',
                    },
                    {
                        label: '25%',
                        value: '0.25',
                    },
                    {
                        label: '20%',
                        value: '0.20',
                    },
                    {
                        label: '15%',
                        value: '0.15',
                    },
                    {
                        label: '10%',
                        value: '0.10',
                    },
                    {
                        label: '5%',
                        value: '0.05',
                    },
                    {
                        label: '1%',
                        value: '0.01',
                    },
                    {
                        label: '0% (replay disabled)',
                        value: '0.00',
                    },
                ]}
                value={value}
            />
        </AccessControlAction>
    )
}
