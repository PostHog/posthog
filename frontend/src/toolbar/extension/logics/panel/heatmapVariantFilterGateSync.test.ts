import { HeatmapVariantFilterGateInputs, heatmapVariantFilterGateToSend } from './heatmapVariantFilterGateSync'

describe('heatmapVariantFilterGateToSend', () => {
    test.each<[string, HeatmapVariantFilterGateInputs, boolean | null]>([
        ['panel flags not loaded yet', { panelFlagsLoaded: false, panelGate: false, pageGate: true }, null],
        ['page state not received yet', { panelFlagsLoaded: true, panelGate: true, pageGate: null }, null],
        ['page already has the gate', { panelFlagsLoaded: true, panelGate: true, pageGate: true }, null],
        ['page restarted with the gate off', { panelFlagsLoaded: true, panelGate: true, pageGate: false }, true],
        ['flag turned off', { panelFlagsLoaded: true, panelGate: false, pageGate: true }, false],
    ])('%s', (_, inputs, expected) => {
        expect(heatmapVariantFilterGateToSend(inputs)).toBe(expected)
    })
})
