import { type ComponentType, Suspense, memo, useContext, useLayoutEffect } from 'react'

import { IconLineGraph, IconPuzzle, IconWarning, IconWrench } from '@posthog/icons'
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle, IconStack, IconStackItem, Skeleton } from '@posthog/quill'

import type { PanelType } from './panelDefinition'
import { PanelErrorBoundary } from './PanelErrorBoundary'
import { PanelHostContext } from './panelHostContext'
import { type SavedPanel } from './panelSchema'

// A panel that suspends before its query starts would otherwise let the load end without it.
function HoldsLoad(): null {
    const { timing } = useContext(PanelHostContext)
    useLayoutEffect(() => timing?.hold(), [timing])
    return null
}

/** Why a panel shows a message instead of its content. */
export type PanelProblem = 'error' | 'unknownType' | 'invalidSettings' | 'failedQuery' | 'empty'

function ProblemIcon({ icon, color }: { icon: JSX.Element; color: string }): JSX.Element {
    return (
        <IconStack>
            <IconStackItem color={color}>{icon}</IconStackItem>
        </IconStack>
    )
}

// Icons and colors match the quill states on v1 insights, so a tile reads the same on both dashboards.
const ILLUSTRATIONS: Record<PanelProblem, JSX.Element> = {
    error: <ProblemIcon icon={<IconWarning />} color="var(--destructive-foreground)" />,
    unknownType: <ProblemIcon icon={<IconPuzzle />} color="var(--warning-foreground)" />,
    invalidSettings: <ProblemIcon icon={<IconWrench />} color="var(--warning-foreground)" />,
    failedQuery: <ProblemIcon icon={<IconWarning />} color="var(--destructive-foreground)" />,
    empty: <ProblemIcon icon={<IconLineGraph />} color="var(--color-product-product-analytics-light)" />,
}

const LINE_WIDTHS = ['w-3/4', 'w-full', 'w-5/6', 'w-2/3']

/** Lines of text, which fit any panel better than one block, since the panel's shape is not known yet. */
export function PanelLoading(): JSX.Element {
    return (
        <div className="flex min-h-0 flex-1 flex-col gap-2 overflow-hidden" aria-busy="true">
            {LINE_WIDTHS.map((width) => (
                <Skeleton key={width} className={`h-3 shrink-0 ${width}`} />
            ))}
        </div>
    )
}

/**
 * A title and an optional line of detail in place of a panel's content, such as when it is empty, fails or can't be
 * shown. A narrow tile gets smaller text and a smaller picture, so the title is never cut off.
 */
export function PanelMessage({
    problem,
    title,
    description,
}: {
    problem?: PanelProblem
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
 * Memoised on the panel, its definition and `setConfig`, which all keep their identity through every layout edit, so
 * moving tiles never re-renders it.
 */
export const PanelView = memo(function PanelView({
    panel,
    definition,
    setConfig,
}: {
    panel: SavedPanel
    definition: PanelType | undefined
    setConfig?: (config: unknown) => void
}): JSX.Element {
    if (!definition) {
        return (
            <PanelMessage
                problem="unknownType"
                title="This panel type isn't available"
                description="This dashboard can't show panels of this type."
            />
        )
    }
    if (definition.configError(panel.config)) {
        return (
            <PanelMessage
                problem="invalidSettings"
                title="This panel's settings aren't valid"
                description="Its saved settings don't match its panel type."
            />
        )
    }
    const Loading: ComponentType<{ panel: SavedPanel }> = definition.Loading ?? PanelLoading
    // One panel that throws or suspends shows its own state, and the rest of the dashboard keeps working.
    return (
        <PanelErrorBoundary
            panel={panel}
            fallback={
                <PanelMessage
                    problem="error"
                    title="This panel hit an error"
                    description="Refresh the page, and if it keeps happening contact support."
                />
            }
        >
            <Suspense
                fallback={
                    <>
                        <HoldsLoad />
                        <Loading panel={panel} />
                    </>
                }
            >
                <definition.Component panel={panel} setConfig={setConfig} />
            </Suspense>
        </PanelErrorBoundary>
    )
})
