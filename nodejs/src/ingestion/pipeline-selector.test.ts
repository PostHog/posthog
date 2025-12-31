import { selectPipelineFactory } from './pipeline-selector'
import { pipelines } from './pipelines-registry'

describe('selectPipelineFactory', () => {
    describe('valid selections', () => {
        it.each([
            ['general', null, null],
            ['general', 'default', null],
            ['general', 'default', 'default'],
            ['general', 'overflow', null],
            ['general', 'overflow', 'default'],
            ['general', 'historical', 'default'],
            ['general', 'async', 'default'],
        ])('selects pipeline for pipeline=%s, lane=%s, implementation=%s', (pipelineName, lane, implementation) => {
            const factory = selectPipelineFactory(pipelineName, lane, implementation)
            expect(factory).toBeDefined()
            expect(typeof factory).toBe('function')
        })

        it('uses default lane when lane is null', () => {
            const factory = selectPipelineFactory('general', null, null)
            const defaultFactory = selectPipelineFactory('general', 'default', 'default')
            expect(factory).toBe(defaultFactory)
        })

        it('uses default lane when lane is undefined', () => {
            const factory = selectPipelineFactory('general', undefined, null)
            const defaultFactory = selectPipelineFactory('general', 'default', 'default')
            expect(factory).toBe(defaultFactory)
        })

        it('uses default implementation when implementation is null', () => {
            const factory = selectPipelineFactory('general', 'overflow', null)
            const defaultFactory = selectPipelineFactory('general', 'overflow', 'default')
            expect(factory).toBe(defaultFactory)
        })
    })

    describe('invalid selections', () => {
        it('throws for unknown pipeline', () => {
            expect(() => selectPipelineFactory('nonexistent', null, null)).toThrow(
                "Unknown pipeline: 'nonexistent'. Available pipelines: general"
            )
        })

        it('throws for unknown lane', () => {
            expect(() => selectPipelineFactory('general', 'nonexistent', null)).toThrow(
                "Unknown lane 'nonexistent' for pipeline 'general'. Available lanes: default, overflow, historical, async"
            )
        })

        it('throws for unknown implementation', () => {
            expect(() => selectPipelineFactory('general', 'default', 'nonexistent')).toThrow(
                "Unknown implementation 'nonexistent' for lane 'default' in pipeline 'general'. Available implementations: default"
            )
        })
    })

    describe('registry structure', () => {
        it('has general pipeline in registry', () => {
            expect(pipelines['general']).toBeDefined()
        })

        it('general pipeline has default lane', () => {
            expect(pipelines['general'].lanes['default']).toBeDefined()
        })

        it('general pipeline has overflow lane', () => {
            expect(pipelines['general'].lanes['overflow']).toBeDefined()
        })

        it('general pipeline has historical lane', () => {
            expect(pipelines['general'].lanes['historical']).toBeDefined()
        })

        it('general pipeline has async lane', () => {
            expect(pipelines['general'].lanes['async']).toBeDefined()
        })

        it('each lane has default implementation', () => {
            for (const laneName of Object.keys(pipelines['general'].lanes)) {
                expect(pipelines['general'].lanes[laneName].implementations['default']).toBeDefined()
            }
        })
    })
})
