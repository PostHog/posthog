import { type ComponentType, type ReactNode, Suspense, memo } from 'react'

import * as errorHoggie from '@posthog/brand/hoggies/png/error'
import { Skeleton } from '@posthog/quill'

import { pngHoggie } from 'lib/brand/hoggies'

import type { SavedWidget } from '../dashboard/document/dashboardTypes'
import type { WidgetType } from './widgetDefinition'
import { WidgetErrorBoundary } from './WidgetErrorBoundary'

const HedgehogError = pngHoggie(errorHoggie)

export function WidgetLoading(): JSX.Element {
    return (
        <div className="flex min-h-0 flex-1 flex-col" aria-busy="true">
            <Skeleton className="h-full w-full" />
        </div>
    )
}

/** A short message in place of a widget's content, such as when it fails or can't be shown. */
export function WidgetMessage({
    illustration,
    children,
}: {
    illustration?: ReactNode
    children: ReactNode
}): JSX.Element {
    return (
        <div className="flex h-full min-h-0 flex-col items-center justify-center gap-2 overflow-hidden text-secondary text-sm">
            {illustration}
            {children}
        </div>
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
    if (!definition) {
        return <WidgetMessage>This dashboard can't show this widget type.</WidgetMessage>
    }
    const Loading: ComponentType<{ widget: SavedWidget }> = definition.Loading ?? WidgetLoading
    // One widget that throws or suspends shows its own state, and the rest of the dashboard keeps working.
    return (
        <WidgetErrorBoundary
            widget={widget}
            fallback={
                <WidgetMessage illustration={<HedgehogError className="size-16 shrink-0" />}>
                    This widget hit an error.
                </WidgetMessage>
            }
        >
            <Suspense fallback={<Loading widget={widget} />}>
                <definition.Component widget={widget} setConfig={setConfig} />
            </Suspense>
        </WidgetErrorBoundary>
    )
})
