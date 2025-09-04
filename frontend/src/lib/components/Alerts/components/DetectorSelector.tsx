import { Group } from 'kea-forms'

import { LemonSelect } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { DetectorType } from '~/queries/schema/schema-general'

export interface DetectorSelectorProps {
    value?: DetectorType
    onChange: (value: DetectorType) => void
    'data-attr'?: string
}

export function DetectorSelector({ value, onChange, 'data-attr': dataAttr }: DetectorSelectorProps): JSX.Element {
    return (
        <div className="flex gap-4 items-center">
            <div>Detector</div>
            <Group name={['detector_config']}>
                <LemonField name="type" className="flex-auto">
                    <LemonSelect
                        fullWidth
                        data-attr={dataAttr}
                        value={value || DetectorType.THRESHOLD}
                        onChange={onChange}
                        options={[
                            {
                                label: 'Threshold',
                                value: DetectorType.THRESHOLD,
                                tooltip: 'Simple upper/lower bounds detection. Best for known thresholds.',
                            },
                            {
                                label: 'Z-Score',
                                value: DetectorType.ZSCORE,
                                tooltip:
                                    'Statistical outlier detection using standard deviation. Good for normally distributed data.',
                            },
                            {
                                label: 'MAD',
                                value: DetectorType.MAD,
                                tooltip:
                                    'Robust outlier detection using median absolute deviation. Better for data with extreme outliers.',
                            },
                        ]}
                    />
                </LemonField>
            </Group>
        </div>
    )
}
