import { getEffectiveAccessMethod } from './NewSourceScene'
import { resolveCreateDirectQueryEnabled } from './sourceWizardLogic'

describe('NewSourceWizard', () => {
    describe('getEffectiveAccessMethod', () => {
        it('uses the draft access method on step 2', () => {
            expect(getEffectiveAccessMethod(2, 'direct', 'warehouse')).toEqual('direct')
        })

        it('falls back to the persisted access method outside step 2', () => {
            expect(getEffectiveAccessMethod(3, 'direct', 'warehouse')).toEqual('warehouse')
        })
    })

    describe('resolveCreateDirectQueryEnabled', () => {
        it.each<[string, { access_method?: string; direct_query_enabled?: boolean }, string, boolean | undefined]>([
            ['synced direct-capable source defaults to enabled', {}, 'Postgres', true],
            ['toggle switched off is respected', { direct_query_enabled: false }, 'Postgres', false],
            ['pure direct source omits the flag', { access_method: 'direct' }, 'Postgres', undefined],
            ['non-direct-capable source omits the flag', {}, 'Stripe', undefined],
        ])('%s', (_description, sourceValues, connectorName, expected) => {
            expect(resolveCreateDirectQueryEnabled(sourceValues, connectorName)).toEqual(expected)
        })
    })
})
