declare module 'react-window' {
    import type {
        CSSProperties,
        HTMLAttributes,
        ReactElement,
        ReactNode,
        MutableRefObject,
        Dispatch,
        SetStateAction,
    } from 'react'

    export interface ListImperativeAPI {
        readonly element: HTMLDivElement | null
        scrollToRow(config: {
            align?: 'auto' | 'center' | 'end' | 'smart' | 'start'
            behavior?: 'auto' | 'instant' | 'smooth'
            index: number
        }): void
    }

    export interface DynamicRowHeight {
        getAverageRowHeight(): number
        getRowHeight(index: number): number | undefined
        setRowHeight(index: number, size: number): void
        observeRowElements: (elements: Element[] | NodeListOf<Element>) => () => void
    }

    export interface ListProps<RowProps extends object = object>
        extends Omit<HTMLAttributes<HTMLDivElement>, 'onResize'> {
        children?: ReactNode
        className?: string
        defaultHeight?: number
        listRef?: MutableRefObject<ListImperativeAPI | undefined>
        onResize?: (size: { height: number; width: number }, prevSize: { height: number; width: number }) => void
        onRowsRendered?: (
            visibleRows: { startIndex: number; stopIndex: number },
            allRows: { startIndex: number; stopIndex: number }
        ) => void
        overscanCount?: number
        rowComponent: (
            props: {
                ariaAttributes: Record<string, unknown>
                index: number
                style: CSSProperties
            } & RowProps
        ) => ReactElement | null
        rowCount: number
        rowHeight: number | string | ((index: number, cellProps: RowProps) => number) | DynamicRowHeight
        rowProps: RowProps
        style?: CSSProperties
        tagName?: keyof JSX.IntrinsicElements
    }

    export function List<RowProps extends object = object>(props: ListProps<RowProps>): ReactElement

    export function useListRef(): MutableRefObject<ListImperativeAPI | undefined>
    export function useListCallbackRef(): [ListImperativeAPI | null, Dispatch<SetStateAction<ListImperativeAPI | null>>]

    export function useDynamicRowHeight(config: { defaultRowHeight: number; key?: string | number }): DynamicRowHeight
}
