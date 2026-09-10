import { defaultDestinationIds, shouldShowDestinationStep, toggleDestinationId } from './destinationStepUtils'

const WAREHOUSE = { id: 'wh', is_posthog_warehouse: true }
const POSTGRES = { id: 'pg', is_posthog_warehouse: false }

const visible = {
    flagEnabled: true,
    isDirectQueryMode: false,
    schemas: [{ should_sync: true, sync_type: 'full_refresh' }],
    requiredTables: undefined,
} as Parameters<typeof shouldShowDestinationStep>[0]

describe('destination step', () => {
    describe('shouldShowDestinationStep', () => {
        it('asks for destinations on an ordinary import', () => {
            expect(shouldShowDestinationStep(visible)).toBe(true)
        })

        it.each([
            ['the flag is off', { flagEnabled: false }],
            ['the source is queried directly rather than imported', { isDirectQueryMode: true }],
            ['a caller drives the wizard to a fixed table list', { requiredTables: ['charges'] }],
        ])('does not ask when %s', (_label, override) => {
            expect(shouldShowDestinationStep({ ...visible, ...override })).toBe(false)
        })

        it('does not ask when a table syncs by CDC, which stays warehouse-only', () => {
            expect(
                shouldShowDestinationStep({
                    ...visible,
                    schemas: [
                        { should_sync: true, sync_type: 'full_refresh' },
                        { should_sync: true, sync_type: 'cdc' },
                    ],
                })
            ).toBe(false)
        })

        it('still asks when a CDC table is present but not being synced', () => {
            expect(
                shouldShowDestinationStep({
                    ...visible,
                    schemas: [{ should_sync: false, sync_type: 'cdc' }],
                })
            ).toBe(true)
        })
    })

    describe('defaultDestinationIds', () => {
        it('starts on the PostHog warehouse, so skipping the step changes nothing', () => {
            expect(defaultDestinationIds([POSTGRES, WAREHOUSE], [])).toEqual(['wh'])
        })

        it('keeps an existing choice, so stepping back and forth does not reset it', () => {
            expect(defaultDestinationIds([POSTGRES, WAREHOUSE], ['pg'])).toEqual(['pg'])
        })

        it('selects nothing when the team has no warehouse destination row yet', () => {
            expect(defaultDestinationIds([POSTGRES], [])).toEqual([])
        })
    })

    describe('toggleDestinationId', () => {
        it('adds one that is off', () => {
            expect(toggleDestinationId(['wh'], 'pg')).toEqual(['wh', 'pg'])
        })

        it('removes one that is on', () => {
            expect(toggleDestinationId(['wh', 'pg'], 'pg')).toEqual(['wh'])
        })
    })
})
