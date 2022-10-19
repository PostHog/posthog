import * as React from 'react'
import { CellMeasurerCacheDecorator } from './CellMeasurerCacheDecorator'
import { Grid, GridCellProps, GridProps, ScrollbarPresenceParams, ScrollParams } from 'react-virtualized/dist/es/Grid'
import { CellMeasurerCache } from 'react-virtualized/dist/es/CellMeasurer'
const SCROLLBAR_SIZE_BUFFER = 20
const MINIMUM_SCROLL_AREA = 150
const FLOAT_HEADER_AT = 56
/**
 * Renders 1, 2, or 4 Grids depending on configuration.
 * A main (body) Grid will always be rendered.
 * Optionally, 1-2 Grids for sticky header rows will also be rendered.
 * If no sticky columns, only 1 sticky header Grid will be rendered.
 * If sticky columns, 2 sticky header Grids will be rendered.
 */

interface MultiGridProps extends GridProps {
    classNameBottomLeftGrid?: string
    classNameBottomRightGrid?: string
    classNameTopLeftGrid?: string
    classNameTopRightGrid?: string
    enableFixedRowScroll?: boolean
    fixedColumnCount: number
    fixedRowCount: number
    style?: React.CSSProperties
    styleBottomLeftGrid?: React.CSSProperties
    styleBottomRightGrid?: React.CSSProperties
    styleTopLeftGrid?: React.CSSProperties
    styleTopRightGrid?: React.CSSProperties
    hideTopRightGridScrollbar?: boolean
    hideBottomLeftGridScrollbar?: boolean
    columnWidth: number | ((opts: { index: number }) => number)
}
enum HeaderState {
    Top = 'top',
    Bottom = 'bottom',
    Fixed = 'fixed',
}
interface MultiGridState {
    scrollLeft: number
    scrollTop: number
    scrollbarSize: number
    showHorizontalScrollbar: boolean
    showVerticalScrollbar: boolean
    headerState: HeaderState
    windowHeight: number
}
export class MultiGrid extends React.PureComponent<MultiGridProps, MultiGridState> {
    static defaultProps: Partial<MultiGridProps> = {
        classNameBottomLeftGrid: '',
        classNameBottomRightGrid: '',
        classNameTopLeftGrid: '',
        classNameTopRightGrid: '',
        enableFixedRowScroll: false,
        fixedColumnCount: 0,
        fixedRowCount: 0,
        scrollToColumn: -1,
        scrollToRow: -1,
        style: {},
        styleBottomLeftGrid: {},
        styleBottomRightGrid: {},
        styleTopLeftGrid: {},
        styleTopRightGrid: {},
        hideTopRightGridScrollbar: false,
        hideBottomLeftGridScrollbar: false,
    }
    state = {
        scrollLeft: 0,
        scrollTop: 0,
        scrollbarSize: 0,
        showHorizontalScrollbar: false,
        showVerticalScrollbar: false,
        headerState: HeaderState.Top,
        windowHeight: typeof window !== undefined ? window.innerHeight : 0,
    }
    _deferredMeasurementCacheBottomLeftGrid?: CellMeasurerCache
    _deferredMeasurementCacheBottomRightGrid?: CellMeasurerCache
    _deferredMeasurementCacheTopRightGrid?: CellMeasurerCache

    _bottomLeftGrid?: Grid
    _bottomRightGrid?: Grid
    _topLeftGrid?: Grid
    _topRightGrid?: Grid
    _container?: HTMLDivElement

    _bottomLeftGridStyle?: React.CSSProperties
    _bottomRightGridStyle?: React.CSSProperties
    _topLeftGridStyle?: React.CSSProperties
    _topRightGridStyle?: React.CSSProperties
    _leftScrollHelperStyle?: React.CSSProperties
    _rightScrollHelperStyle?: React.CSSProperties

    _lastRenderedStyleBottomLeftGrid?: React.CSSProperties
    _lastRenderedStyleBottomRightGrid?: React.CSSProperties
    _lastRenderedStyleTopLeftGrid?: React.CSSProperties
    _lastRenderedStyleTopRightGrid?: React.CSSProperties

    _containerTopStyle?: React.CSSProperties
    _containerBottomStyle?: React.CSSProperties
    _containerOuterStyle?: React.CSSProperties

    _lastRenderedWidth?: number
    _lastRenderedColumnWidth?: number | ((opts: { index: number }) => number)
    _lastRenderedFixedColumnCount?: number
    _lastRenderedFixedRowCount?: number
    _lastRenderedHeight?: number
    _lastRenderedRowHeight?: number | ((opts: { index: number }) => number)
    _lastRenderedStyle?: React.CSSProperties
    _lastRenderedEnoughSpaceForFixedColumns?: boolean
    _lastRenderedHeaderState?: HeaderState

    _leftGridWidth?: number | null
    _topGridHeight?: number | null
    _scrollWidth?: number | null

    _deferredInvalidateColumnIndex?: number
    _deferredInvalidateRowIndex?: number

    constructor(props: MultiGridProps, context: any) {
        super(props, context)
        const { deferredMeasurementCache, fixedColumnCount, fixedRowCount } = props

        this._maybeCalculateCachedStyles(true)

        if (deferredMeasurementCache) {
            this._deferredMeasurementCacheBottomLeftGrid =
                fixedRowCount > 0
                    ? new CellMeasurerCacheDecorator({
                          cellMeasurerCache: deferredMeasurementCache,
                          columnIndexOffset: 0,
                          rowIndexOffset: fixedRowCount,
                      })
                    : deferredMeasurementCache
            this._deferredMeasurementCacheBottomRightGrid =
                fixedColumnCount > 0 || fixedRowCount > 0
                    ? new CellMeasurerCacheDecorator({
                          cellMeasurerCache: deferredMeasurementCache,
                          columnIndexOffset: fixedColumnCount,
                          rowIndexOffset: fixedRowCount,
                      })
                    : deferredMeasurementCache
            this._deferredMeasurementCacheTopRightGrid =
                fixedColumnCount > 0
                    ? new CellMeasurerCacheDecorator({
                          cellMeasurerCache: deferredMeasurementCache,
                          columnIndexOffset: fixedColumnCount,
                          rowIndexOffset: 0,
                      })
                    : deferredMeasurementCache
        }
    }

    forceUpdateGrids(): void {
        this._bottomLeftGrid?.forceUpdate()
        this._bottomRightGrid?.forceUpdate()
        this._topLeftGrid?.forceUpdate()
        this._topRightGrid?.forceUpdate()
    }

    /** See Grid#invalidateCellSizeAfterRender */
    invalidateCellSizeAfterRender({ columnIndex = 0, rowIndex = 0 } = {}): void {
        this._deferredInvalidateColumnIndex =
            typeof this._deferredInvalidateColumnIndex === 'number'
                ? Math.min(this._deferredInvalidateColumnIndex, columnIndex)
                : columnIndex
        this._deferredInvalidateRowIndex =
            typeof this._deferredInvalidateRowIndex === 'number'
                ? Math.min(this._deferredInvalidateRowIndex, rowIndex)
                : rowIndex
    }

    /** See Grid#measureAllCells */
    measureAllCells(): void {
        this._bottomLeftGrid?.measureAllCells()
        this._bottomRightGrid?.measureAllCells()
        this._topLeftGrid?.measureAllCells()
        this._topRightGrid?.measureAllCells()
    }

    /** See Grid#recomputeGridSize */
    recomputeGridSize({ columnIndex = 0, rowIndex = 0 } = {}): void {
        const { fixedColumnCount, fixedRowCount } = this.props
        const adjustedColumnIndex = Math.max(0, columnIndex - fixedColumnCount)
        const adjustedRowIndex = Math.max(0, rowIndex - fixedRowCount)
        this._bottomLeftGrid &&
            this._bottomLeftGrid.recomputeGridSize({
                columnIndex,
                rowIndex: adjustedRowIndex,
            })
        this._bottomRightGrid &&
            this._bottomRightGrid.recomputeGridSize({
                columnIndex: adjustedColumnIndex,
                rowIndex: adjustedRowIndex,
            })
        this._topLeftGrid &&
            this._topLeftGrid.recomputeGridSize({
                columnIndex,
                rowIndex,
            })
        this._topRightGrid &&
            this._topRightGrid.recomputeGridSize({
                columnIndex: adjustedColumnIndex,
                rowIndex,
            })
        this._leftGridWidth = null
        this._scrollWidth = null
        this._topGridHeight = null

        this._maybeCalculateCachedStyles(true)
    }

    static getDerivedStateFromProps(
        nextProps: MultiGridProps,
        prevState: MultiGridState
    ): Partial<MultiGridState> | null {
        if (nextProps.scrollLeft !== prevState.scrollLeft) {
            return {
                scrollLeft:
                    nextProps.scrollLeft != null && nextProps.scrollLeft >= 0
                        ? nextProps.scrollLeft
                        : prevState.scrollLeft,
            }
        }

        return null
    }

    componentDidMount(): void {
        const { scrollLeft } = this.props

        if ((scrollLeft ?? 0) > 0) {
            this.setState({
                scrollLeft: scrollLeft ?? 0,
            })
        }

        this._handleInvalidatedGridSize()
        this._handleWindowScrollResize()

        window.addEventListener('scroll', this._handleWindowScrollResize)
        window.addEventListener('resize', this._handleWindowScrollResize)
    }

    componentWillUnmount(): void {
        window.removeEventListener('scroll', this._handleWindowScrollResize)
        window.removeEventListener('resize', this._handleWindowScrollResize)
    }

    componentDidUpdate(): void {
        this._handleInvalidatedGridSize()
    }

    render(): JSX.Element | null {
        const {
            onScroll,
            onSectionRendered,
            onScrollbarPresenceChange,
            scrollLeft: scrollLeftProp,
            scrollToColumn,
            scrollTop: scrollTopProp,
            scrollToRow,
            ...rest
        } = this.props

        this._prepareForRender()

        // Don't render any of our Grids if there are no cells.
        // This mirrors what Grid does,
        // And prevents us from recording inaccurage measurements when used with CellMeasurer.
        if (this.props.width === 0 || this.props.height === 0) {
            return null
        }

        // scrollTop and scrollLeft props are explicitly filtered out and ignored
        const { scrollLeft, scrollTop } = this.state
        return (
            <div style={this._containerOuterStyle} ref={this._containerRef}>
                <div style={this._containerTopStyle}>
                    {this._renderTopLeftGrid(rest)}
                    {this._renderTopRightGrid({ ...rest, onScroll, scrollLeft })}
                    {this._renderScrollHelpers(false)}
                </div>
                <div style={this._containerBottomStyle}>
                    {this._renderBottomLeftGrid({ ...rest, onScroll, scrollTop })}
                    {this._renderBottomRightGrid({
                        ...rest,
                        onScroll,
                        onSectionRendered,
                        scrollLeft,
                        scrollToColumn,
                        scrollToRow,
                        scrollTop,
                    })}
                    {this._renderScrollHelpers(true)}
                </div>
            </div>
        )
    }

    _renderScrollHelpers(adjustScrollHeight: boolean): JSX.Element {
        const { scrollLeft, showHorizontalScrollbar, scrollbarSize } = this.state
        const { width } = this.props
        return (
            <>
                {scrollLeft > 0 ? (
                    <div
                        style={
                            adjustScrollHeight && showHorizontalScrollbar
                                ? {
                                      ...this._leftScrollHelperStyle,
                                      bottom: adjustScrollHeight && showHorizontalScrollbar ? scrollbarSize : 0,
                                  }
                                : this._leftScrollHelperStyle
                        }
                    />
                ) : null}
                {scrollLeft < this._getScrollWidth() - width ? (
                    <div
                        style={
                            adjustScrollHeight && showHorizontalScrollbar
                                ? {
                                      ...this._rightScrollHelperStyle,
                                      bottom: adjustScrollHeight && showHorizontalScrollbar ? scrollbarSize : 0,
                                  }
                                : this._rightScrollHelperStyle
                        }
                    />
                ) : null}
            </>
        )
    }

    _bottomLeftGridRef = (ref: Grid): void => {
        this._bottomLeftGrid = ref
    }
    _bottomRightGridRef = (ref: Grid): void => {
        this._bottomRightGrid = ref
    }
    _cellRendererBottomLeftGrid = ({ rowIndex, ...rest }: GridCellProps): React.ReactNode => {
        const { cellRenderer, fixedRowCount, rowCount } = this.props

        if (rowIndex === rowCount - fixedRowCount) {
            return <div key={rest.key} style={{ ...rest.style, height: SCROLLBAR_SIZE_BUFFER }} />
        } else {
            return cellRenderer({
                ...rest,
                parent: this,
                rowIndex: rowIndex + fixedRowCount,
            })
        }
    }
    _cellRendererBottomRightGrid = ({ columnIndex, rowIndex, ...rest }: GridCellProps): React.ReactNode => {
        const { cellRenderer, fixedColumnCount, fixedRowCount } = this.props
        const fixedColumns = this._enoughSpaceForFixedColumns() ? fixedColumnCount : 0
        return cellRenderer({
            ...rest,
            columnIndex: columnIndex + fixedColumns,
            parent: this,
            rowIndex: rowIndex + fixedRowCount,
        })
    }
    _cellRendererTopRightGrid = ({ columnIndex, ...rest }: GridCellProps): React.ReactNode => {
        const { cellRenderer, columnCount, fixedColumnCount } = this.props
        const fixedColumns = this._enoughSpaceForFixedColumns() ? fixedColumnCount : 0

        if (columnIndex === columnCount - fixedColumns) {
            return <div key={rest.key} style={{ ...rest.style, width: SCROLLBAR_SIZE_BUFFER }} />
        } else {
            return cellRenderer({
                ...rest,
                columnIndex: columnIndex + fixedColumns,
                parent: this,
            })
        }
    }
    _columnWidthRightGrid = ({ index }: { index: number }): number => {
        const { columnCount, fixedColumnCount, columnWidth } = this.props
        const { scrollbarSize, showHorizontalScrollbar } = this.state

        // An extra cell is added to the count
        // This gives the smaller Grid extra room for offset,
        // In case the main (bottom right) Grid has a scrollbar
        // If no scrollbar, the extra space is overflow:hidden anyway
        if (showHorizontalScrollbar && index === columnCount - fixedColumnCount) {
            return scrollbarSize
        }

        return typeof columnWidth === 'function'
            ? columnWidth({
                  index: index + fixedColumnCount,
              })
            : columnWidth
    }

    _getLeftGridWidth(): number {
        const { fixedColumnCount, columnWidth } = this.props

        if (this._leftGridWidth == null) {
            if (typeof columnWidth === 'function') {
                let leftGridWidth = 0

                for (let index = 0; index < fixedColumnCount; index++) {
                    leftGridWidth += columnWidth({
                        index,
                    })
                }

                this._leftGridWidth = leftGridWidth
            } else {
                this._leftGridWidth = columnWidth * fixedColumnCount
            }
        }

        return this._leftGridWidth
    }

    _getScrollWidth(): number {
        const { columnCount, columnWidth } = this.props

        if (this._scrollWidth == null) {
            if (typeof columnWidth === 'function') {
                let leftGridWidth = 0

                for (let index = 0; index < columnCount; index++) {
                    leftGridWidth += columnWidth({
                        index,
                    })
                }

                this._scrollWidth = leftGridWidth
            } else {
                this._scrollWidth = columnWidth * columnCount
            }
        }

        return this._scrollWidth
    }

    _getRightGridWidth(): number {
        const { width } = this.props
        const leftGridWidth = this._getLeftGridWidth()

        return width - leftGridWidth
    }

    _getTopGridHeight(): number {
        const { fixedRowCount, rowHeight } = this.props

        if (this._topGridHeight == null) {
            if (typeof rowHeight === 'function') {
                let topGridHeight = 0

                for (let index = 0; index < fixedRowCount; index++) {
                    topGridHeight += rowHeight({
                        index,
                    })
                }

                this._topGridHeight = topGridHeight
            } else {
                this._topGridHeight = rowHeight * fixedRowCount
            }
        }

        return this._topGridHeight
    }

    _handleInvalidatedGridSize(): void {
        if (typeof this._deferredInvalidateColumnIndex === 'number') {
            const columnIndex = this._deferredInvalidateColumnIndex
            const rowIndex = this._deferredInvalidateRowIndex
            this._deferredInvalidateColumnIndex = undefined
            this._deferredInvalidateRowIndex = undefined
            this.recomputeGridSize({
                columnIndex,
                rowIndex,
            })
            this.forceUpdate()
        }
    }

    _enoughSpaceForFixedColumns(): boolean {
        return this.props.fixedColumnCount > 0 && this._getLeftGridWidth() <= this.props.width - MINIMUM_SCROLL_AREA
    }

    /**
     * Avoid recreating inline styles each render; this bypasses Grid's shallowCompare.
     * This method recalculates styles only when specific props change.
     */
    _maybeCalculateCachedStyles(resetAll?: boolean): void {
        const {
            columnWidth,
            enableFixedRowScroll,
            height,
            fixedColumnCount,
            fixedRowCount,
            rowHeight,
            style,
            styleBottomLeftGrid,
            styleBottomRightGrid,
            styleTopLeftGrid,
            styleTopRightGrid,
            width,
        } = this.props
        const { headerState } = this.state
        const sizeChange = resetAll || height !== this._lastRenderedHeight || width !== this._lastRenderedWidth
        const leftSizeChange =
            resetAll ||
            columnWidth !== this._lastRenderedColumnWidth ||
            fixedColumnCount !== this._lastRenderedFixedColumnCount ||
            this._enoughSpaceForFixedColumns() !== this._lastRenderedEnoughSpaceForFixedColumns ||
            width !== this._lastRenderedWidth
        const topSizeChange =
            resetAll || fixedRowCount !== this._lastRenderedFixedRowCount || rowHeight !== this._lastRenderedRowHeight
        const headerStateChange = resetAll || headerState !== this._lastRenderedHeaderState

        if (resetAll || sizeChange || style !== this._lastRenderedStyle) {
            this._containerOuterStyle = {
                height,
                overflow: 'visible',
                // Let :focus outline show through
                width,
                position: 'relative',
                zIndex: 1,
                ...style,
            }
        }

        if (resetAll || sizeChange || topSizeChange || headerStateChange) {
            this._containerTopStyle = {
                height: this._getTopGridHeight(),
                width,
                ...(headerState === HeaderState.Fixed
                    ? { position: 'fixed', top: FLOAT_HEADER_AT, zIndex: 3 }
                    : { position: 'relative', zIndex: 3 }),
            }
            this._containerBottomStyle = {
                height: headerState === HeaderState.Fixed ? height : height - this._getTopGridHeight(),
                overflow: 'visible',
                // Let :focus outline show through
                position: 'relative',
                zIndex: 2,
                width,
                ...(headerState !== HeaderState.Top ? { paddingTop: this._getTopGridHeight() } : {}),
            }

            this._leftScrollHelperStyle = {
                boxShadow: '16px 0 16px -16px rgba(0, 0, 0, 0.25) inset',
                width: 16,
                pointerEvents: 'none',
                position: 'absolute',
                top: 0,
                bottom: 0,
                left: this._enoughSpaceForFixedColumns() ? this._getLeftGridWidth() : 0,
                zIndex: 22,
            }
            this._rightScrollHelperStyle = {
                boxShadow: '-16px 0 16px -16px rgba(0, 0, 0, 0.25) inset',
                width: 16,
                pointerEvents: 'none',
                position: 'absolute',
                top: 0,
                right: 0,
                bottom: 0,
                zIndex: 22,
            }
        }

        if (resetAll || styleBottomLeftGrid !== this._lastRenderedStyleBottomLeftGrid) {
            this._bottomLeftGridStyle = {
                left: 0,
                overflowX: 'hidden',
                overflowY: 'hidden',
                position: 'absolute',
                zIndex: 10,
                ...styleBottomLeftGrid,
            }
        }

        if (resetAll || leftSizeChange || styleBottomRightGrid !== this._lastRenderedStyleBottomRightGrid) {
            this._bottomRightGridStyle = {
                left: 0,
                paddingLeft: this._enoughSpaceForFixedColumns() ? this._getLeftGridWidth() : 0,
                position: 'absolute',
                zIndex: 2,
                width,
                ...styleBottomRightGrid,
            }
        }

        if (resetAll || styleTopLeftGrid !== this._lastRenderedStyleTopLeftGrid) {
            this._topLeftGridStyle = {
                left: 0,
                overflowX: 'hidden',
                overflowY: 'hidden',
                position: 'absolute',
                top: 0,
                zIndex: 11,
                ...styleTopLeftGrid,
            }
        }

        if (resetAll || leftSizeChange || styleTopRightGrid !== this._lastRenderedStyleTopRightGrid) {
            this._topRightGridStyle = {
                left: 0,
                paddingLeft: this._enoughSpaceForFixedColumns() ? this._getLeftGridWidth() : 0,
                overflowX: enableFixedRowScroll ? 'auto' : 'hidden',
                overflowY: 'hidden',
                position: 'absolute',
                top: 0,
                zIndex: 2,
                width,
                ...styleTopRightGrid,
            }
        }

        this._lastRenderedColumnWidth = columnWidth
        this._lastRenderedFixedColumnCount = fixedColumnCount
        this._lastRenderedFixedRowCount = fixedRowCount
        this._lastRenderedHeight = height
        this._lastRenderedRowHeight = rowHeight
        this._lastRenderedStyle = style
        this._lastRenderedStyleBottomLeftGrid = styleBottomLeftGrid
        this._lastRenderedStyleBottomRightGrid = styleBottomRightGrid
        this._lastRenderedStyleTopLeftGrid = styleTopLeftGrid
        this._lastRenderedStyleTopRightGrid = styleTopRightGrid
        this._lastRenderedWidth = width
        this._lastRenderedEnoughSpaceForFixedColumns = this._enoughSpaceForFixedColumns()
        this._lastRenderedHeaderState = this.state.headerState
    }

    _prepareForRender(): void {
        if (
            this._lastRenderedColumnWidth !== this.props.columnWidth ||
            this._lastRenderedFixedColumnCount !== this.props.fixedColumnCount ||
            this._lastRenderedEnoughSpaceForFixedColumns !== this._enoughSpaceForFixedColumns()
        ) {
            this._leftGridWidth = null
            this._scrollWidth = null
        }

        if (
            this._lastRenderedFixedRowCount !== this.props.fixedRowCount ||
            this._lastRenderedRowHeight !== this.props.rowHeight
        ) {
            this._topGridHeight = null
        }

        this._maybeCalculateCachedStyles()

        this._lastRenderedColumnWidth = this.props.columnWidth
        this._lastRenderedFixedColumnCount = this.props.fixedColumnCount
        this._lastRenderedFixedRowCount = this.props.fixedRowCount
        this._lastRenderedRowHeight = this.props.rowHeight
        this._lastRenderedEnoughSpaceForFixedColumns = this._enoughSpaceForFixedColumns()
    }

    _onScrollbarPresenceChange = ({ horizontal, size, vertical }: ScrollbarPresenceParams): void => {
        const { showHorizontalScrollbar, showVerticalScrollbar } = this.state

        if (horizontal !== showHorizontalScrollbar || vertical !== showVerticalScrollbar) {
            this.setState({
                scrollbarSize: size,
                showHorizontalScrollbar: horizontal,
                showVerticalScrollbar: vertical,
            })
            const { onScrollbarPresenceChange } = this.props

            if (typeof onScrollbarPresenceChange === 'function') {
                onScrollbarPresenceChange({
                    horizontal,
                    size,
                    vertical,
                })
            }
        }
    }

    _onScrollLeft = (scrollInfo: ScrollParams): void => {
        this.setState({ scrollLeft: scrollInfo.scrollLeft })
        this.props.onScroll?.(scrollInfo)
    }

    _handleWindowScrollResize = (): void => {
        const { scrollTop, headerState, windowHeight } = this.state
        const containerY = this._container?.getBoundingClientRect()?.y ?? 0
        const newScrollTop = containerY < FLOAT_HEADER_AT ? FLOAT_HEADER_AT - containerY : 0
        const newHeaderState = containerY > FLOAT_HEADER_AT ? HeaderState.Top : HeaderState.Fixed
        const newWindowHeight = window.innerHeight

        if (newScrollTop !== scrollTop || newHeaderState !== headerState || newWindowHeight !== windowHeight) {
            this.setState({
                scrollTop: newScrollTop,
                headerState: newHeaderState,
                windowHeight: newWindowHeight,
            })
        }
    }

    _getBottomGridHeight(): number {
        return this.props.height - this._getTopGridHeight()
    }

    _renderBottomLeftGrid(props: GridProps): React.ReactNode {
        const { fixedColumnCount, fixedRowCount, rowCount, hideBottomLeftGridScrollbar } = props
        const { showVerticalScrollbar, windowHeight } = this.state

        if (!fixedColumnCount || !this._enoughSpaceForFixedColumns()) {
            return null
        }

        const additionalRowCount = showVerticalScrollbar ? 1 : 0,
            height = this._getBottomGridHeight(),
            width = this._getLeftGridWidth(),
            scrollbarSize = this.state.showVerticalScrollbar ? this.state.scrollbarSize : 0,
            gridWidth = hideBottomLeftGridScrollbar ? width + scrollbarSize : width

        const bottomLeftGrid = (
            <Grid
                {...props}
                cellRenderer={this._cellRendererBottomLeftGrid}
                className={this.props.classNameBottomLeftGrid}
                columnCount={fixedColumnCount}
                deferredMeasurementCache={this._deferredMeasurementCacheBottomLeftGrid}
                height={windowHeight}
                ref={this._bottomLeftGridRef}
                rowCount={Math.max(0, rowCount - fixedRowCount) + additionalRowCount}
                rowHeight={this._rowHeightBottomGrid}
                style={this._bottomLeftGridStyle}
                tabIndex={null}
                width={gridWidth}
            />
        )

        if (hideBottomLeftGridScrollbar) {
            return (
                <div
                    className="BottomLeftGrid_ScrollWrapper"
                    style={{
                        ...this._bottomLeftGridStyle,
                        height,
                        width,
                        overflowY: 'hidden',
                    }}
                >
                    {bottomLeftGrid}
                </div>
            )
        }

        return bottomLeftGrid
    }

    _renderBottomRightGrid(props: GridProps): React.ReactNode {
        const { columnCount, fixedColumnCount, fixedRowCount, rowCount, scrollToColumn, scrollToRow } = props
        const { windowHeight } = this.state
        const fixedColumns = this._enoughSpaceForFixedColumns() ? fixedColumnCount : 0
        return (
            <Grid
                {...props}
                cellRenderer={this._cellRendererBottomRightGrid}
                className={this.props.classNameBottomRightGrid}
                columnCount={Math.max(0, columnCount - fixedColumns)}
                columnWidth={fixedColumns ? this._columnWidthRightGrid : this.props.columnWidth}
                deferredMeasurementCache={
                    fixedColumns
                        ? this._deferredMeasurementCacheBottomRightGrid
                        : this._deferredMeasurementCacheBottomLeftGrid
                }
                height={windowHeight}
                onScroll={this._onScrollLeft}
                onScrollbarPresenceChange={this._onScrollbarPresenceChange}
                ref={this._bottomRightGridRef}
                rowCount={Math.max(0, rowCount - fixedRowCount)}
                rowHeight={this._rowHeightBottomGrid}
                scrollToColumn={typeof scrollToColumn === 'number' ? scrollToColumn - fixedColumns : scrollToColumn}
                scrollToRow={typeof scrollToRow === 'number' ? scrollToRow - fixedRowCount : scrollToRow}
                style={this._bottomRightGridStyle}
                width={fixedColumns ? this._getRightGridWidth() : this.props.width}
            />
        )
    }

    _renderTopLeftGrid(props: GridProps): React.ReactNode {
        const { fixedColumnCount, fixedRowCount } = props

        if (!fixedColumnCount || !fixedRowCount || !this._enoughSpaceForFixedColumns()) {
            return null
        }

        return (
            <Grid
                {...props}
                className={props.classNameTopLeftGrid}
                columnCount={fixedColumnCount}
                height={this._getTopGridHeight()}
                ref={this._topLeftGridRef}
                rowCount={fixedRowCount}
                style={this._topLeftGridStyle}
                tabIndex={null}
                width={this._getLeftGridWidth()}
            />
        )
    }

    _renderTopRightGrid(props: GridProps): React.ReactNode {
        const {
            columnCount,
            enableFixedRowScroll,
            fixedColumnCount,
            fixedRowCount,
            scrollLeft,
            hideTopRightGridScrollbar,
            // width,
        } = props
        const { showHorizontalScrollbar, scrollbarSize } = this.state

        if (!fixedRowCount) {
            return null
        }

        const fixedColumns = this._enoughSpaceForFixedColumns() ? fixedColumnCount : 0
        const height = this._getTopGridHeight(),
            width = fixedColumns ? this._getRightGridWidth() : this.props.width,
            additionalHeight = showHorizontalScrollbar ? scrollbarSize : 0

        let gridHeight = height,
            style = this._topRightGridStyle

        if (hideTopRightGridScrollbar) {
            gridHeight = height + additionalHeight
            style = { ...this._topRightGridStyle, left: 0, width: this.props.width }
        }

        const topRightGrid = (
            <Grid
                {...props}
                cellRenderer={this._cellRendererTopRightGrid}
                className={props.classNameTopRightGrid}
                columnCount={Math.max(0, columnCount - fixedColumns)}
                columnWidth={fixedColumns ? this._columnWidthRightGrid : this.props.columnWidth}
                deferredMeasurementCache={
                    fixedColumns ? this._deferredMeasurementCacheTopRightGrid : this.props.deferredMeasurementCache
                }
                height={gridHeight}
                onScroll={enableFixedRowScroll ? this._onScrollLeft : undefined}
                ref={this._topRightGridRef}
                rowCount={fixedRowCount}
                scrollLeft={scrollLeft}
                style={style}
                tabIndex={null}
                width={width}
            />
        )

        if (hideTopRightGridScrollbar) {
            return (
                <div
                    className="TopRightGrid_ScrollWrapper"
                    style={{
                        ...this._topRightGridStyle,
                        height,
                        width,
                        overflowX: 'hidden',
                    }}
                >
                    {topRightGrid}
                </div>
            )
        }

        return topRightGrid
    }

    _rowHeightBottomGrid = ({ index }: { index: number }): number => {
        const { fixedRowCount, rowCount, rowHeight } = this.props
        const { scrollbarSize, showVerticalScrollbar } = this.state

        // An extra cell is added to the count
        // This gives the smaller Grid extra room for offset,
        // In case the main (bottom right) Grid has a scrollbar
        // If no scrollbar, the extra space is overflow:hidden anyway
        if (showVerticalScrollbar && index === rowCount - fixedRowCount) {
            return scrollbarSize
        }

        return typeof rowHeight === 'function'
            ? rowHeight({
                  index: index + fixedRowCount,
              })
            : rowHeight
    }

    _topLeftGridRef = (ref: Grid): void => {
        this._topLeftGrid = ref
    }

    _topRightGridRef = (ref: Grid): void => {
        this._topRightGrid = ref
    }

    _containerRef = (ref: HTMLDivElement): void => {
        this._container = ref
    }
}
