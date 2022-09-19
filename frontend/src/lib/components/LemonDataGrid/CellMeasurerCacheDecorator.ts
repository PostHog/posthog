// https://github.com/bvaughn/react-virtualized/blob/master/source/MultiGrid/CellMeasurerCacheDecorator.js
import { CellMeasurerCache } from 'react-virtualized/dist/es/CellMeasurer'

type CellMeasurerCacheDecoratorParams = {
    cellMeasurerCache: CellMeasurerCache
    columnIndexOffset: number
    rowIndexOffset: number
}

type IndexParam = {
    index: number
}

/**
 * Caches measurements for a given cell.
 */
export class CellMeasurerCacheDecorator implements CellMeasurerCache {
    _cellMeasurerCache: CellMeasurerCache
    _columnIndexOffset: number
    _rowIndexOffset: number
    defaultHeight: number
    defaultWidth: number

    constructor(params: CellMeasurerCacheDecoratorParams) {
        this._cellMeasurerCache = params.cellMeasurerCache
        this._columnIndexOffset = params.columnIndexOffset
        this._rowIndexOffset = params.rowIndexOffset
        this.defaultHeight = this._cellMeasurerCache.defaultHeight
        this.defaultWidth = this._cellMeasurerCache.defaultWidth
    }

    clear(rowIndex: number, columnIndex: number): void {
        this._cellMeasurerCache.clear(rowIndex + this._rowIndexOffset, columnIndex + this._columnIndexOffset)
    }

    clearAll(): void {
        this._cellMeasurerCache.clearAll()
    }

    columnWidth = ({ index }: IndexParam): number => {
        return this._cellMeasurerCache.columnWidth({
            index: index + this._columnIndexOffset,
        })
    }

    hasFixedHeight(): boolean {
        return this._cellMeasurerCache.hasFixedHeight()
    }

    hasFixedWidth(): boolean {
        return this._cellMeasurerCache.hasFixedWidth()
    }

    getHeight(rowIndex: number, columnIndex = 0): number {
        return this._cellMeasurerCache.getHeight(rowIndex + this._rowIndexOffset, columnIndex + this._columnIndexOffset)
    }

    getWidth(rowIndex: number, columnIndex = 0): number {
        return this._cellMeasurerCache.getWidth(rowIndex + this._rowIndexOffset, columnIndex + this._columnIndexOffset)
    }

    has(rowIndex: number, columnIndex = 0): boolean {
        return this._cellMeasurerCache.has(rowIndex + this._rowIndexOffset, columnIndex + this._columnIndexOffset)
    }

    rowHeight = ({ index }: IndexParam): number => {
        return this._cellMeasurerCache.rowHeight({
            index: index + this._rowIndexOffset,
        })
    }

    set(rowIndex: number, columnIndex: number, width: number, height: number): void {
        this._cellMeasurerCache.set(
            rowIndex + this._rowIndexOffset,
            columnIndex + this._columnIndexOffset,
            width,
            height
        )
    }
}
