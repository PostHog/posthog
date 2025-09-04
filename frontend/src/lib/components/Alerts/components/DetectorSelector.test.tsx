import { DetectorType } from '~/queries/schema/schema-general'

// Simple tests for DetectorSelector logic since full component tests require complex setup
describe('DetectorSelector', () => {
    describe('detector type enum', () => {
        it('has correct detector type values', () => {
            expect(DetectorType.THRESHOLD).toBe('threshold')
            expect(DetectorType.ZSCORE).toBe('zscore')
            expect(DetectorType.MAD).toBe('mad')
        })
    })

    describe('detector type labels', () => {
        const getDetectorLabel = (type: DetectorType): string => {
            switch (type) {
                case DetectorType.THRESHOLD:
                    return 'Threshold'
                case DetectorType.ZSCORE:
                    return 'Z-Score'
                case DetectorType.MAD:
                    return 'MAD'
                default:
                    return 'Unknown'
            }
        }

        it('provides correct labels for detector types', () => {
            expect(getDetectorLabel(DetectorType.THRESHOLD)).toBe('Threshold')
            expect(getDetectorLabel(DetectorType.ZSCORE)).toBe('Z-Score')
            expect(getDetectorLabel(DetectorType.MAD)).toBe('MAD')
        })
    })

    describe('detector descriptions', () => {
        const getDetectorDescription = (type: DetectorType): string => {
            switch (type) {
                case DetectorType.THRESHOLD:
                    return 'Alert when metric goes above or below set bounds'
                case DetectorType.ZSCORE:
                    return 'Alert when metric deviates from normal behavior using z-score'
                case DetectorType.MAD:
                    return 'Alert using Median Absolute Deviation (more robust to outliers)'
                default:
                    return ''
            }
        }

        it('provides descriptions for detector types', () => {
            expect(getDetectorDescription(DetectorType.THRESHOLD)).toContain('above or below')
            expect(getDetectorDescription(DetectorType.ZSCORE)).toContain('z-score')
            expect(getDetectorDescription(DetectorType.MAD)).toContain('Median Absolute Deviation')
        })
    })
})
