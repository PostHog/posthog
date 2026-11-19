import type { Panel } from '../spec'
import type { DataFrame } from './frame'

export interface ViewerProps<Options> {
    frames: DataFrame[]
    panel: Panel
    options: Options
    height: number
    width: number
    onEditPanel?: (edit: (panel: Panel) => Panel) => void
}

export interface LogsOptions {
    histogram: boolean
    wrap: boolean
    fontSize: 'small' | 'medium' | 'large'
    columns?: string[]
    prettify: boolean
}

export interface TracesOptions {
    histogram: boolean
}

export function logsOptionsOf(panel: Panel): LogsOptions {
    const options = panel.viz.options ?? {}
    return {
        histogram: options.histogram !== false,
        wrap: options.wrap === true,
        fontSize: options.fontSize === 'medium' || options.fontSize === 'large' ? options.fontSize : 'small',
        columns: Array.isArray(options.columns) ? (options.columns as string[]) : undefined,
        prettify: options.prettify === true,
    }
}

export const tracesOptionsOf = (panel: Panel): TracesOptions => ({ histogram: panel.viz.options?.histogram !== false })
