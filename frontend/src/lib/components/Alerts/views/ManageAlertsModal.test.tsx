import { DetectionDirection, DetectorType, InsightThresholdType } from '~/queries/schema/schema-general'

import { AlertType } from '../types'
import { formatDetectorParameters } from './ManageAlertsModal'

describe('formatDetectorParameters', () => {
    describe('Threshold detectors', () => {
        it('formats absolute thresholds correctly', () => {
            const alert: Partial<AlertType> = {
                threshold: {
                    configuration: {
                        bounds: { lower: 10, upper: 100 },
                        type: InsightThresholdType.ABSOLUTE,
                    },
                },
            }

            expect(formatDetectorParameters(alert as AlertType)).toBe('Low 10 · High 100')
        })

        it('formats percentage thresholds correctly', () => {
            const alert: Partial<AlertType> = {
                threshold: {
                    configuration: {
                        bounds: { lower: 0.1, upper: 0.9 },
                        type: InsightThresholdType.PERCENTAGE,
                    },
                },
            }

            expect(formatDetectorParameters(alert as AlertType)).toBe('Low 10% · High 90%')
        })

        it('handles upper threshold only', () => {
            const alert: Partial<AlertType> = {
                threshold: {
                    configuration: {
                        bounds: { upper: 50 },
                        type: InsightThresholdType.ABSOLUTE,
                    },
                },
            }

            expect(formatDetectorParameters(alert as AlertType)).toBe('High 50')
        })

        it('handles lower threshold only', () => {
            const alert: Partial<AlertType> = {
                threshold: {
                    configuration: {
                        bounds: { lower: 25 },
                        type: InsightThresholdType.ABSOLUTE,
                    },
                },
            }

            expect(formatDetectorParameters(alert as AlertType)).toBe('Low 25')
        })
    })

    describe('Z-Score detectors', () => {
        it('formats Z-Score parameters correctly', () => {
            const alert: Partial<AlertType> = {
                detector_config: {
                    type: DetectorType.ZSCORE,
                    value_type: 'raw' as any,
                    config: {
                        threshold: 2.5,
                        direction: DetectionDirection.BOTH,
                        min_samples: 10,
                        window_size: 50,
                    } as any,
                },
            }

            expect(formatDetectorParameters(alert as AlertType)).toBe('Z-Score 2.5 (both, raw)')
        })

        it('handles Z-Score with up direction and delta value type', () => {
            const alert: Partial<AlertType> = {
                detector_config: {
                    type: DetectorType.ZSCORE,
                    value_type: 'delta' as any,
                    config: {
                        threshold: 3.0,
                        direction: DetectionDirection.UP,
                    } as any,
                },
            }

            expect(formatDetectorParameters(alert as AlertType)).toBe('Z-Score 3 (up, delta)')
        })

        it('uses default threshold when not provided', () => {
            const alert: Partial<AlertType> = {
                detector_config: {
                    type: DetectorType.ZSCORE,
                    value_type: 'raw' as any,
                    config: {
                        direction: DetectionDirection.DOWN,
                    } as any,
                },
            }

            expect(formatDetectorParameters(alert as AlertType)).toBe('Z-Score 2 (down, raw)')
        })
    })

    describe('MAD detectors', () => {
        it('formats MAD parameters correctly', () => {
            const alert: Partial<AlertType> = {
                detector_config: {
                    type: DetectorType.MAD,
                    value_type: 'delta' as any,
                    config: {
                        threshold: 4.0,
                        direction: DetectionDirection.UP,
                        min_samples: 15,
                        window_size: 100,
                    } as any,
                },
            }

            expect(formatDetectorParameters(alert as AlertType)).toBe('MAD 4 (up, delta)')
        })

        it('uses default threshold for MAD when not provided', () => {
            const alert: Partial<AlertType> = {
                detector_config: {
                    type: DetectorType.MAD,
                    value_type: 'raw' as any,
                    config: {
                        direction: DetectionDirection.BOTH,
                    } as any,
                },
            }

            expect(formatDetectorParameters(alert as AlertType)).toBe('MAD 3 (both, raw)')
        })
    })

    describe('Edge cases', () => {
        it('returns null for alert with no configuration', () => {
            const alert: Partial<AlertType> = {}

            expect(formatDetectorParameters(alert as AlertType)).toBeNull()
        })

        it('returns null for threshold with no bounds', () => {
            const alert: Partial<AlertType> = {
                threshold: {
                    configuration: {
                        bounds: {},
                        type: InsightThresholdType.ABSOLUTE,
                    },
                },
            }

            expect(formatDetectorParameters(alert as AlertType)).toBeNull()
        })

        it('returns null for detector with no config', () => {
            const alert: Partial<AlertType> = {
                detector_config: {
                    type: DetectorType.ZSCORE,
                    value_type: 'raw' as any,
                    config: null as any,
                },
            }

            expect(formatDetectorParameters(alert as AlertType)).toBeNull()
        })

        it('handles default values correctly', () => {
            const alert: Partial<AlertType> = {
                detector_config: {
                    type: DetectorType.ZSCORE,
                    // No value_type provided
                    config: {
                        // No threshold or direction provided
                    } as any,
                },
            }

            expect(formatDetectorParameters(alert as AlertType)).toBe('Z-Score 2 (both, raw)')
        })
    })
})
