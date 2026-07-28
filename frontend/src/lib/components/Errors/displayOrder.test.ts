import { toDisplayOrderFrames } from './displayOrder'
import { ErrorTrackingStackFrame } from './types'

describe('toDisplayOrderFrames', () => {
    const frame = (fn: string): ErrorTrackingStackFrame =>
        ({ raw_id: fn, mangled_name: fn, in_app: true, resolved: false, lang: 'javascript' }) as ErrorTrackingStackFrame

    it('shows the crash site first from canonical bottom-up storage', () => {
        const stored = [frame('main'), frame('handler'), frame('crash')]
        const display = toDisplayOrderFrames(stored)
        expect(display.map((f) => f.raw_id)).toEqual(['crash', 'handler', 'main'])
        // stored input is not mutated
        expect(stored.map((f) => f.raw_id)).toEqual(['main', 'handler', 'crash'])
    })
})
