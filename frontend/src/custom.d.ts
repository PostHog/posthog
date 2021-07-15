// This fixes TS errors when importing a .svg file
declare module '*.svg' {
    const content: any
    export default content
}
// This fixes TS errors when importing a .png file
declare module '*.png' {
    const content: any
    export default content
}

// Rough outline of funnel-graph-js types, as no official ones exist

declare module 'funnel-graph-js' {
    interface FunnelGraphParams {
        container: string
        data: {
            colors: string[]
            labels: string[]
            values: number[]
        }
        direction?: 'horizontal' | 'vertical'
        gradientDirection?: 'horizontal' | 'vertical'
        displayPercent?: boolean
        width?: number
        height?: number
        subLabelValue?: 'percent' | 'raw'
    }

    export default class FunnelGraph implements FunnelGraphParams {
        constructor(params: FunnelGraphParams) {}
        container: string | HTMLElement | null
        createContainer: (params: any) => unknown
        graphContainer: HTMLElement
        data: {
            colors: string[]
            labels: string[]
            values: number[]
        }
        draw: () => unknown
        makeVertical: () => unknown
        makeHorizontal: () => unknown
        toggleDirection: () => unknown
        gradientMakeVertical: () => unknown
        gradientMakeHorizontal: () => unknown
        gradientToggleDirection: () => unknown
        updateHeight: () => unknown
        updateWidth: () => unknown
        updateData: (data: any) => unknown
        update: (options: any) => unknown
        direction: 'horizontal' | 'vertical'
        gradientDirection: 'horizontal' | 'vertical'
        displayPercent: boolean
        width: number
        height: number
        subLabelValue: 'percent' | 'raw'
    }
}
