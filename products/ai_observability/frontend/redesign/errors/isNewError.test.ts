import type { TraceCellLoad } from '../shared/cellLoads'
import type { ErrorFirstSeen } from './errorFirstSeenLogic'
import { isNewError } from './isNewError'

const READ = { firstSeen: '2026-09-02T08:30:00Z', checkedFrom: '2026-08-02' }

describe('isNewError', () => {
    it.each<[string, TraceCellLoad<ErrorFirstSeen> | undefined, boolean]>([
        ['not asked for yet', undefined, false],
        ['loading', { status: 'loading' }, false],
        ['failed', { status: 'error' }, false],
        ['read and not new', { status: 'ready', value: { ...READ, isNew: false } }, false],
        ['read and new', { status: 'ready', value: { ...READ, isNew: true } }, true],
    ])('is %s: %s', (_name, load, isNew) => {
        expect(isNewError(load)).toBe(isNew)
    })
})
