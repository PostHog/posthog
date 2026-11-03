import type { DotMatrixProps } from '../types'

export type DotMatrixMockDatasetName = 'product_activity' | 'people' | 'ci'
export interface DotMatrixMockPerson {
    id: string
    name: string
    email: string
    seconds: number
}
export interface DotMatrixMockDatum extends Record<string, unknown> {
    rowKey: string
    columnKey: string
    seriesKey: string
    value: number
    persons: DotMatrixMockPerson[]
}
export interface DotMatrixMockAccount {
    id: string
    name: string
    logo: string
    u: Record<string, number[]>
}
export type DotMatrixMockDataset = DotMatrixProps<DotMatrixMockDatum>
