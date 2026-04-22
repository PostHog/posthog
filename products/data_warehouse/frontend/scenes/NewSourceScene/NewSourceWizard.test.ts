import { getEffectiveAccessMethod } from './NewSourceScene'

describe('NewSourceWizard', () => {
    describe('getEffectiveAccessMethod', () => {
        it('uses the draft access method on step 2', () => {
            expect(getEffectiveAccessMethod(2, 'direct', 'warehouse')).toEqual('direct')
        })

        it('falls back to the persisted access method outside step 2', () => {
            expect(getEffectiveAccessMethod(3, 'direct', 'warehouse')).toEqual('warehouse')
        })
    })
})
