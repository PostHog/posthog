import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { hogSenseLogic } from './hogSenseLogic'
import type { DetectionEntry } from './types'

describe('hogSenseLogic', () => {
    beforeEach(() => {
        initKeaTests()
    })

    it('returns empty findings when no entries match', () => {
        const entries: DetectionEntry<{ active: boolean }>[] = [
            {
                id: 'test-entry',
                trigger: (ctx) => ctx.active,
                summary: 'Active',
                description: 'This is active',
                severity: 'info',
            },
        ]

        const logic = hogSenseLogic({ key: 'test-empty', entries, context: { active: false } })
        logic.mount()

        expectLogic(logic).toMatchValues({ findings: [] })
    })

    it('returns findings for matching entries', () => {
        const entries: DetectionEntry<{ active: boolean }>[] = [
            {
                id: 'test-entry',
                trigger: (ctx) => ctx.active,
                summary: 'Active',
                description: 'This is active',
                severity: 'warning',
                docs: [{ label: 'Learn more', url: 'https://example.com' }],
            },
        ]

        const logic = hogSenseLogic({ key: 'test-match', entries, context: { active: true } })
        logic.mount()

        expectLogic(logic).toMatchValues({
            findings: [
                {
                    id: 'test-entry',
                    summary: 'Active',
                    description: 'This is active',
                    severity: 'warning',
                    docs: [{ label: 'Learn more', url: 'https://example.com' }],
                    entityType: undefined,
                    entityId: undefined,
                },
            ],
        })
    })

    it('preserves entity metadata on findings', () => {
        const entries: DetectionEntry<{ value: number }>[] = [
            {
                id: 'threshold',
                trigger: (ctx) => ctx.value > 100,
                summary: 'Over threshold',
                description: 'Value exceeds 100',
                severity: 'error',
            },
        ]

        const logic = hogSenseLogic({
            key: 'test-entity',
            entries,
            context: { value: 200 },
            entityType: 'feature_flag',
            entityId: 42,
        })
        logic.mount()

        expectLogic(logic).toMatchValues({
            findings: [
                expect.objectContaining({
                    id: 'threshold',
                    entityType: 'feature_flag',
                    entityId: 42,
                }),
            ],
        })
    })

    it('returns multiple findings when multiple entries match', () => {
        const entries: DetectionEntry<{ a: boolean; b: boolean }>[] = [
            {
                id: 'entry-a',
                trigger: (ctx) => ctx.a,
                summary: 'A is true',
                description: 'A',
                severity: 'info',
            },
            {
                id: 'entry-b',
                trigger: (ctx) => ctx.b,
                summary: 'B is true',
                description: 'B',
                severity: 'warning',
            },
            {
                id: 'entry-c',
                trigger: () => false,
                summary: 'Never',
                description: 'C',
                severity: 'error',
            },
        ]

        const logic = hogSenseLogic({ key: 'test-multi', entries, context: { a: true, b: true } })
        logic.mount()

        expectLogic(logic).toMatchValues({
            findings: [expect.objectContaining({ id: 'entry-a' }), expect.objectContaining({ id: 'entry-b' })],
        })
    })

    it('returns empty findings for empty entries array', () => {
        const logic = hogSenseLogic({ key: 'test-no-entries', entries: [], context: {} })
        logic.mount()

        expectLogic(logic).toMatchValues({ findings: [] })
    })
})
