import { DetectionDirection, DetectorType, InsightThresholdType, ValueType } from '~/queries/schema/schema-general'

import { AlertFormType } from '../alertFormLogic'
import { DetectorSelector } from './DetectorSelector'
import { StatisticalConfiguration } from './StatisticalConfiguration'
import { ThresholdConfiguration } from './ThresholdConfiguration'
import { ValueTypeSelector } from './ValueTypeSelector'

export interface DetectorConfigurationProps {
    alertForm: AlertFormType
    setAlertFormValue: (key: string, value: any) => void
}

export function DetectorConfiguration({ alertForm, setAlertFormValue }: DetectorConfigurationProps): JSX.Element {
    const handleDetectorTypeChange = (value: DetectorType): void => {
        // Reset detector config when detector type changes
        if (value === DetectorType.THRESHOLD) {
            setAlertFormValue('detector_config', {
                type: DetectorType.THRESHOLD,
                value_type: ValueType.RAW,
                config: {
                    bounds: alertForm.threshold.configuration.bounds,
                    threshold_type:
                        alertForm.threshold.configuration.type === InsightThresholdType.PERCENTAGE
                            ? 'percentage'
                            : 'absolute',
                },
            })
        } else if (value === DetectorType.ZSCORE) {
            setAlertFormValue('detector_config', {
                type: DetectorType.ZSCORE,
                value_type: ValueType.RAW,
                config: {
                    threshold: 2.0,
                    direction: DetectionDirection.BOTH,
                    min_samples: 10,
                    window_size: 50,
                },
            })
        } else if (value === DetectorType.MAD) {
            setAlertFormValue('detector_config', {
                type: DetectorType.MAD,
                value_type: ValueType.RAW,
                config: {
                    threshold: 3.0,
                    direction: DetectionDirection.BOTH,
                    min_samples: 10,
                    window_size: 50,
                },
            })
        }
    }

    const handleValueTypeChange = (value: ValueType): void => {
        setAlertFormValue('detector_config', {
            ...alertForm.detector_config,
            value_type: value,
        })
    }

    const detectorType = alertForm.detector_config?.type
    const isThreshold = detectorType === DetectorType.THRESHOLD || !detectorType
    const isStatistical = detectorType === DetectorType.ZSCORE || detectorType === DetectorType.MAD

    return (
        <div className="deprecated-space-y-4">
            {/* Detector Type Selection */}
            <DetectorSelector
                value={alertForm.detector_config?.type}
                onChange={handleDetectorTypeChange}
                data-attr="alertForm-detector-type"
            />

            {/* Detector Configuration */}
            {isThreshold && <ThresholdConfiguration alertForm={alertForm} setAlertFormValue={setAlertFormValue} />}

            {detectorType === DetectorType.ZSCORE && (
                <StatisticalConfiguration
                    alertForm={alertForm}
                    detectorType={DetectorType.ZSCORE}
                    setAlertFormValue={setAlertFormValue}
                />
            )}

            {detectorType === DetectorType.MAD && (
                <StatisticalConfiguration
                    alertForm={alertForm}
                    detectorType={DetectorType.MAD}
                    setAlertFormValue={setAlertFormValue}
                />
            )}

            {/* Value Type Selection (for statistical detectors) */}
            {isStatistical && (
                <ValueTypeSelector value={alertForm.detector_config?.value_type} onChange={handleValueTypeChange} />
            )}
        </div>
    )
}
