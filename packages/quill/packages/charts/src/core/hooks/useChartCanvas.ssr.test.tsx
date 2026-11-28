import { renderToString } from 'react-dom/server'

import { LineChart } from '../../charts/LineChart/LineChart'

describe('useChartCanvas server rendering', () => {
    // The shared Jest setup needs jsdom, so this file cannot use the node environment.
    // Remove `window` for each test instead, which is the global that server rendering lacks.
    const windowDescriptor = Object.getOwnPropertyDescriptor(globalThis, 'window')!

    beforeEach(() => {
        delete (globalThis as { window?: Window }).window
    })

    afterEach(() => {
        Object.defineProperty(globalThis, 'window', windowDescriptor)
    })

    it('renders LineChart without window', () => {
        const html = renderToString(
            <LineChart series={[{ key: 'a', label: 'A', data: [10, 20, 30] }]} labels={['Mon', 'Tue', 'Wed']} />
        )
        expect(html).toContain('<canvas')
    })
})
