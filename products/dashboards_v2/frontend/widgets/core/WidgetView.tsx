import { type ComponentType, Suspense, memo, useContext, useLayoutEffect } from 'react'

import * as constructionHoggie from '@posthog/brand/hoggies/png/construction-1'
import * as errorHoggie from '@posthog/brand/hoggies/png/error'
import * as panicHoggie from '@posthog/brand/hoggies/png/panic'
import * as puzzleHoggie from '@posthog/brand/hoggies/png/puzzle'
import { IconLineGraph } from '@posthog/icons'
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle, IconStack, IconStackItem, Skeleton } from '@posthog/quill'

import { pngHoggie } from 'lib/brand/hoggies'

import type { SavedWidget } from '../../dashboard/document/dashboardTypes'
import type { WidgetType } from './widgetDefinition'
import { WidgetErrorBoundary } from './WidgetErrorBoundary'
import { WidgetHostContext } from './widgetHostContext'

// A widget that suspends before its query starts would otherwise let the load end without it.
function HoldsLoad(): null {
    const { timing } = useContext(WidgetHostContext)
    useLayoutEffect(() => timing?.hold(), [timing])
    return null
}

const HedgehogError = pngHoggie(errorHoggie)
const HedgehogPuzzle = pngHoggie(puzzleHoggie)
const HedgehogConstruction = pngHoggie(constructionHoggie)
const HedgehogPanic = pngHoggie(panicHoggie)

/** Why a widget shows a message instead of its content. A problem gets a hedgehog, and an empty result an icon. */
export type WidgetProblem = 'error' | 'unknownType' | 'invalidSettings' | 'failedQuery' | 'empty'

const HOGGIE_CLASS = 'size-10 shrink-0 object-contain @min-[20rem]:size-16'

// The empty icon matches the quill empty state on v1 insights, so an empty chart reads the same on both dashboards.
const ILLUSTRATIONS: Record<WidgetProblem, JSX.Element> = {
    error: <HedgehogError className={HOGGIE_CLASS} />,
    unknownType: <HedgehogPuzzle className={HOGGIE_CLASS} />,
    invalidSettings: <HedgehogConstruction className={HOGGIE_CLASS} />,
    failedQuery: <HedgehogPanic className={HOGGIE_CLASS} />,
    empty: (
        <IconStack>
            <IconStackItem color="var(--color-product-product-analytics-light)">
                <IconLineGraph />
            </IconStackItem>
        </IconStack>
    ),
}

const LINE_WIDTHS = ['w-3/4', 'w-full', 'w-5/6', 'w-2/3']

/** Lines of text, which fit any widget better than one block, since the widget's shape is not known yet. */
export function WidgetLoading(): JSX.Element {
    return (
        <div className="flex min-h-0 flex-1 flex-col gap-2 overflow-hidden" aria-busy="true">
            {LINE_WIDTHS.map((width) => (
                <Skeleton key={width} className={`h-3 shrink-0 ${width}`} />
            ))}
        </div>
    )
}

/**
 * A title and an optional line of detail in place of a widget's content, such as when it is empty, fails or can't be
 * shown. A narrow tile gets smaller text and a smaller picture, so the title is never cut off.
 */
export function WidgetMessage({
    problem,
    title,
    description,
}: {
    problem?: WidgetProblem
    title: string
    description?: string
}): JSX.Element {
    return (
        <Empty className="@container min-h-0 flex-1 overflow-hidden border-none p-2 @min-[20rem]:px-4 @min-[20rem]:py-6">
            <EmptyHeader>
                {problem && ILLUSTRATIONS[problem]}
                <EmptyTitle className="text-sm @min-[20rem]:text-lg">{title}</EmptyTitle>
                {description && (
                    <EmptyDescription
                        className="line-clamp-2 text-xs @min-[20rem]:line-clamp-3 @min-[20rem]:text-sm"
                        title={description}
                    >
                        {description}
                    </EmptyDescription>
                )}
            </EmptyHeader>
        </Empty>
    )
}

/**
 * Memoised on the widget, its definition and `setConfig`, which all keep their identity through every layout edit, so
 * moving tiles never re-renders it.
 */
export const WidgetView = memo(function WidgetView({
    widget,
    definition,
    setConfig,
}: {
    widget: SavedWidget
    definition: WidgetType | undefined
    setConfig?: (config: unknown) => void
}): JSX.Element {
    const { sampleData } = useContext(WidgetHostContext)
    if (!definition) {
        return (
            <WidgetMessage
                problem="unknownType"
                title="This widget type isn't available"
                description="This dashboard can't show widgets of this type."
            />
        )
    }
    if (definition.configError(widget.config)) {
        return (
            <WidgetMessage
                problem="invalidSettings"
                title="This widget's settings aren't valid"
                description="Its saved settings don't match its widget type."
            />
        )
    }
    const Loading: ComponentType<{ widget: SavedWidget }> = definition.Loading ?? WidgetLoading
    const SampleData = sampleData ? definition.SampleData : undefined
    // One widget that throws or suspends shows its own state, and the rest of the dashboard keeps working.
    return (
        <WidgetErrorBoundary
            widget={widget}
            fallback={
                <WidgetMessage
                    problem="error"
                    title="This widget hit an error"
                    description="Refresh the page, and if it keeps happening contact support."
                />
            }
        >
            <Suspense
                fallback={
                    <>
                        <HoldsLoad />
                        <Loading widget={widget} />
                    </>
                }
            >
                {SampleData ? (
                    <SampleData widget={widget} />
                ) : (
                    <definition.Component widget={widget} setConfig={setConfig} />
                )}
            </Suspense>
        </WidgetErrorBoundary>
    )
})
