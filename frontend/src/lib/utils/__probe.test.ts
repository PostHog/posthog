import { makeId } from 'lib/utils/__probe_consumer'
import * as libUtils from 'lib/utils/dom'

describe('cross-module mock probe', () => {
    it('mutating dom namespace affects another module that imported uuid', () => {
        ;(libUtils as any).uuid = jest.fn().mockReturnValue('MOCKED')
        expect(makeId()).toBe('MOCKED')
    })
})
