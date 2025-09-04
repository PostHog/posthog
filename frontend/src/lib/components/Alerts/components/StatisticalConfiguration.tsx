import { Group } from 'kea-forms'

import { LemonInput, LemonSelect, Tooltip } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { DetectionDirection, DetectorType } from '~/queries/schema/schema-general'

import { AlertFormType } from '../alertFormLogic'

export interface StatisticalConfigurationProps {
    alertForm: AlertFormType
    detectorType: DetectorType.ZSCORE | DetectorType.MAD
    setAlertFormValue: (key: string, value: any) => void
}

export function StatisticalConfiguration({
    alertForm,
    detectorType,
    setAlertFormValue,
}: StatisticalConfigurationProps): JSX.Element {
    const isZScore = detectorType === DetectorType.ZSCORE
    const thresholdLabel = isZScore ? 'Threshold' : 'Threshold'
    const thresholdTooltip = isZScore
        ? 'Z-score threshold for outlier detection. Higher values = less sensitive. 2.0 catches ~95% of normal data, 3.0 catches ~99.7%'
        : 'MAD threshold for outlier detection. Higher values = less sensitive. More robust to extreme outliers than Z-score'
    const defaultThreshold = isZScore ? '2.0' : '3.0'
    const dataAttrPrefix = isZScore ? 'alertForm-zscore' : 'alertForm-mad'

    return (
        <div className="deprecated-space-y-3">
            <div className="flex gap-4 items-center">
                <div>{thresholdLabel}</div>
                <Group name={['detector_config', 'config']}>
                    <LemonField name="threshold">
                        <Tooltip title={thresholdTooltip}>
                            <LemonInput
                                type="number"
                                className="w-20"
                                placeholder={defaultThreshold}
                                data-attr={`${dataAttrPrefix}-threshold`}
                                min={0.1}
                                step={0.1}
                            />
                        </Tooltip>
                    </LemonField>
                </Group>
                <div>Direction</div>
                <Group name={['detector_config', 'config']}>
                    <LemonField name="direction">
                        <Tooltip title="Which direction of outliers to detect">
                            <LemonSelect
                                className="w-24"
                                data-attr={`${dataAttrPrefix}-direction`}
                                value={alertForm.detector_config?.config?.direction || DetectionDirection.BOTH}
                                onChange={(value) => {
                                    setAlertFormValue('detector_config', {
                                        ...alertForm.detector_config,
                                        config: {
                                            ...alertForm.detector_config?.config,
                                            direction: value,
                                        },
                                    })
                                }}
                                options={[
                                    {
                                        label: 'Both',
                                        value: DetectionDirection.BOTH,
                                    },
                                    {
                                        label: 'Up',
                                        value: DetectionDirection.UP,
                                    },
                                    {
                                        label: 'Down',
                                        value: DetectionDirection.DOWN,
                                    },
                                ]}
                            />
                        </Tooltip>
                    </LemonField>
                </Group>
            </div>
            <div className="flex gap-4 items-center">
                <div>Min samples</div>
                <Group name={['detector_config', 'config']}>
                    <LemonField name="min_samples">
                        <Tooltip title="Minimum number of data points needed before detection starts">
                            <LemonInput
                                type="number"
                                className="w-20"
                                placeholder="10"
                                data-attr={`${dataAttrPrefix}-min-samples`}
                                min={2}
                            />
                        </Tooltip>
                    </LemonField>
                </Group>
                <div>Window size</div>
                <Group name={['detector_config', 'config']}>
                    <LemonField name="window_size">
                        <Tooltip title="Maximum number of recent data points to use for calculations. Leave empty to use all available data">
                            <LemonInput
                                type="number"
                                className="w-20"
                                placeholder="50"
                                data-attr={`${dataAttrPrefix}-window-size`}
                                min={5}
                            />
                        </Tooltip>
                    </LemonField>
                </Group>
            </div>
        </div>
    )
}
