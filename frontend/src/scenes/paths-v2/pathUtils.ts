import { RGBColor } from 'd3'

export interface PathTargetLink {
    average_conversion_time: number
    index: number
    source: PathNodeData
    target: PathNodeData
    value: number
    width: number
    y0: number
    color: RGBColor
}

export interface PathNodeData {
    name: string
    targetLinks: PathTargetLink[]
    sourceLinks: PathTargetLink[]
    depth: number
    width: number
    height: number
    index: number
    value: number
    x0: number
    x1: number
    y0: number
    y1: number
    layer: number
    source: PathNodeData
    target: PathNodeData
}
