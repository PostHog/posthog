export interface HeatmapVariantFilterGateInputs {
    panelFlagsLoaded: boolean
    panelGate: boolean
    pageGate: boolean | null
}

export function heatmapVariantFilterGateToSend({
    panelFlagsLoaded,
    panelGate,
    pageGate,
}: HeatmapVariantFilterGateInputs): boolean | null {
    // Before the panel's flags load, the flag reads as off, which would clear a gate the page already has.
    if (!panelFlagsLoaded || pageGate === null || pageGate === panelGate) {
        return null
    }
    return panelGate
}
