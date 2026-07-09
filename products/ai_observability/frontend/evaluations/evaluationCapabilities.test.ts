import { evaluationSupportsReports } from './evaluationCapabilities'

describe('evaluationCapabilities', () => {
    it('supports reports only for boolean generation-target evaluations', () => {
        expect(evaluationSupportsReports({ output_type: 'boolean', target: 'generation' })).toBe(true)
        expect(evaluationSupportsReports({ output_type: 'boolean', target: 'trace' })).toBe(false)
        expect(evaluationSupportsReports({ output_type: 'sentiment', target: 'generation' })).toBe(false)
    })
})
