import { createEventsToDropByToken } from '../../../src/utils/db/hub'

describe('createEventsToDropByToken', () => {
    it('should split tokens on comma', () => {
        expect(createEventsToDropByToken('x:y,x:z')).toEqual(new Map([['x', ['y', 'z']]]))
    })
    it('handles events with duplicate separators', () => {
        expect(createEventsToDropByToken('x:a,x:y:z,x:b')).toEqual(new Map([['x', ['a', 'y:z', 'b']]]))
    })
})
