import { formatWidgetListCountFooter, WIDGET_LIST_COUNT_ISSUES, type WidgetListCountNoun } from './constants'

export type WidgetListCountFooterProps = {
    shown: number
    totalCount?: number
    totalCountCapped?: boolean
    noun?: WidgetListCountNoun
    hasMore?: boolean
    dataAttr: string
}

export function WidgetListCountFooter({
    shown,
    totalCount,
    totalCountCapped,
    noun = WIDGET_LIST_COUNT_ISSUES,
    hasMore,
    dataAttr,
}: WidgetListCountFooterProps): JSX.Element {
    return (
        <p className="text-xs text-muted m-0 text-center" data-attr={dataAttr}>
            {formatWidgetListCountFooter(shown, totalCount, totalCountCapped, noun, hasMore)}
        </p>
    )
}
