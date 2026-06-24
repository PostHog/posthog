import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { ReactNode } from 'react'

import { IconCursorClick, IconGraph, IconGridMasonry, IconLetter } from '@posthog/icons'
import { LemonTag } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { urls } from 'scenes/urls'

import { addInsightToDashboardLogic } from './addInsightToDashboardModalLogic'
import { DashboardAddTileType, addTilePickerModalLogic } from './addTilePickerModalLogic'
import { dashboardLogic } from './dashboardLogic'

interface TileOption {
    type: DashboardAddTileType
    label: string
    description: string
    icon: JSX.Element
    preview: JSX.Element
    tag?: 'new' | 'beta'
    'data-attr': string
}

/**
 * Chrome shared by the preview tiles: white card with the same compact header a real dashboard tile
 * has (uppercase type • date row, title, ⋯). Header is omitted for freeform tiles (text / button).
 */
function MiniTile({
    type,
    title,
    bodyClassName,
    children,
}: {
    type?: string
    title?: string
    bodyClassName?: string
    children: ReactNode
}): JSX.Element {
    return (
        <div className="flex h-full w-full flex-col overflow-hidden rounded border border-primary bg-surface-primary shadow-sm">
            {type && (
                <>
                    <div className="px-1.5 pt-1">
                        <div className="text-[0.5rem] font-bold uppercase leading-tight tracking-[0.03em] text-secondary">
                            {type}
                        </div>
                        <div className="flex items-center justify-between gap-1">
                            <span className="truncate text-[0.7rem] font-semibold leading-tight text-primary">
                                {title}
                            </span>
                            <span className="shrink-0 text-[0.6rem] leading-none text-secondary">•••</span>
                        </div>
                    </div>
                    <div className="mt-1 border-t border-primary" />
                </>
            )}
            <div className={`min-h-0 flex-1 overflow-hidden ${bodyClassName ?? ''}`}>{children}</div>
        </div>
    )
}

/** A faithful-looking trends line tile — header, smooth line with area fill, faint gridlines, date axis. */
function InsightPreview(): JSX.Element {
    return (
        <MiniTile
            type="Trends • Last 7 days"
            title="Weekly active users"
            bodyClassName="flex flex-col px-1.5 pb-1 pt-1"
        >
            <svg viewBox="0 0 100 34" preserveAspectRatio="none" className="h-full w-full flex-1">
                {[8, 17, 26].map((y) => (
                    <line
                        key={y}
                        x1="0"
                        y1={y}
                        x2="100"
                        y2={y}
                        stroke="var(--color-border-primary)"
                        strokeWidth="0.5"
                    />
                ))}
                <polygon
                    points="0,34 0,27 14,23 28,26 42,15 56,19 70,9 84,12 100,5 100,34"
                    fill="var(--data-color-1)"
                    fillOpacity="0.15"
                />
                <polyline
                    points="0,27 14,23 28,26 42,15 56,19 70,9 84,12 100,5"
                    fill="none"
                    stroke="var(--data-color-1)"
                    strokeWidth="1.5"
                    strokeLinejoin="round"
                    strokeLinecap="round"
                    vectorEffect="non-scaling-stroke"
                />
            </svg>
            <div className="flex justify-between pt-0.5 text-[0.45rem] text-secondary">
                <span>Jun 1</span>
                <span>Jun 8</span>
                <span>Jun 15</span>
                <span>Jun 22</span>
            </div>
        </MiniTile>
    )
}

/** Sample rendered markdown so the user can picture a text card. */
function TextCardPreview(): JSX.Element {
    return (
        <MiniTile bodyClassName="flex flex-col justify-center gap-1 px-2">
            <div className="text-[0.75rem] font-semibold text-primary">Q2 launch goals</div>
            <div className="text-[0.55rem] leading-snug text-secondary">
                Track weekly active users and conversion as we roll out the new onboarding flow.
            </div>
        </MiniTile>
    )
}

/** A non-interactive mock of a button tile. */
function ButtonPreview(): JSX.Element {
    return (
        <MiniTile bodyClassName="flex items-center justify-center">
            <span className="rounded bg-accent px-2 py-1 text-[0.65rem] font-medium text-white">Read the docs →</span>
        </MiniTile>
    )
}

/** A faithful-looking "Top issues" error-tracking widget — ranked issues with sparklines and counts. */
function WidgetPreview(): JSX.Element {
    const issues = [
        {
            title: 'TypeError: Cannot read properties of undefined',
            count: '42',
            bars: ['h-1', 'h-2', 'h-1.5', 'h-2.5', 'h-2', 'h-3', 'h-2'],
        },
        {
            title: 'NetworkError: Failed to fetch',
            count: '18',
            bars: ['h-1', 'h-1.5', 'h-2', 'h-1', 'h-2', 'h-1.5', 'h-1'],
        },
    ]
    return (
        <MiniTile type="Error tracking • Last 7 days" title="Top issues" bodyClassName="flex flex-col">
            <div className="flex items-center justify-between border-b border-primary bg-surface-secondary px-1.5 py-0.5 text-[0.45rem] font-semibold uppercase tracking-wide text-secondary">
                <span>Issue</span>
                <span>Occurrences</span>
            </div>
            <div className="flex-1 divide-y divide-primary">
                {issues.map((issue) => (
                    <div key={issue.title} className="flex items-center gap-1 px-1.5 py-1">
                        <span className="h-1 w-1 shrink-0 rounded-full bg-danger" />
                        <span className="min-w-0 flex-1 truncate text-[0.55rem] font-medium text-primary">
                            {issue.title}
                        </span>
                        <span className="flex h-2.5 items-end gap-px">
                            {issue.bars.map((h, i) => (
                                <span key={i} className={`w-0.5 rounded-sm bg-accent ${h}`} />
                            ))}
                        </span>
                        <span className="w-4 shrink-0 text-right text-[0.55rem] font-semibold tabular-nums text-primary">
                            {issue.count}
                        </span>
                    </div>
                ))}
            </div>
            <div className="border-t border-primary px-1.5 py-0.5 text-center text-[0.45rem] text-secondary">
                2 of 42 issues
            </div>
        </MiniTile>
    )
}

export function AddTilePickerModal(): JSX.Element | null {
    const { dashboard, dashboardWidgetsEnabled } = useValues(dashboardLogic)
    const { setAddWidgetModalOpen } = useActions(dashboardLogic)
    const { addTilePickerModalVisible } = useValues(addTilePickerModalLogic)
    const { hideAddTilePickerModal } = useActions(addTilePickerModalLogic)
    const { showAddInsightToDashboardModal } = useActions(addInsightToDashboardLogic)
    const { reportDashboardAddTileOptionClicked } = useActions(eventUsageLogic)
    const { push } = useActions(router)

    if (!dashboard) {
        return null
    }

    const onSelect = (type: DashboardAddTileType, proceed: () => void): void => {
        reportDashboardAddTileOptionClicked(type, 'test')
        hideAddTilePickerModal()
        proceed()
    }

    const options: TileOption[] = [
        {
            type: 'insight',
            label: 'Insight',
            description: 'Add a trend, funnel, retention, or any saved insight.',
            icon: <IconGraph />,
            preview: <InsightPreview />,
            'data-attr': 'dashboard-picker-insight',
        },
        {
            type: 'text_card',
            label: 'Text card',
            description: 'Add context, notes, or headings in markdown.',
            icon: <IconLetter />,
            preview: <TextCardPreview />,
            'data-attr': 'dashboard-picker-text',
        },
        {
            type: 'button',
            label: 'Button',
            description: 'Link out to docs, runbooks, or related dashboards.',
            icon: <IconCursorClick />,
            preview: <ButtonPreview />,
            'data-attr': 'dashboard-picker-button',
        },
        {
            type: 'widget',
            label: 'Widget',
            description: dashboardWidgetsEnabled
                ? 'Drop in a ready-made widget from across PostHog.'
                : 'Drop in a ready-made widget from across PostHog. Enable it from feature previews first.',
            icon: <IconGridMasonry />,
            preview: <WidgetPreview />,
            tag: dashboardWidgetsEnabled ? 'new' : 'beta',
            'data-attr': 'dashboard-picker-widget',
        },
    ]

    const proceedFor: Record<DashboardAddTileType, () => void> = {
        insight: () => showAddInsightToDashboardModal(),
        text_card: () => push(urls.dashboardTextTile(dashboard.id, 'new')),
        button: () => push(urls.dashboardButtonTile(dashboard.id, 'new')),
        widget: () =>
            dashboardWidgetsEnabled
                ? setAddWidgetModalOpen(true)
                : push(urls.featurePreview(FEATURE_FLAGS.DASHBOARD_WIDGETS)),
    }

    return (
        <LemonModal
            isOpen={addTilePickerModalVisible}
            onClose={hideAddTilePickerModal}
            title="Add to dashboard"
            description="Pick what you'd like to add."
            width={720}
        >
            <div className="grid grid-cols-1 gap-8 sm:grid-cols-2">
                {options.map((option) => (
                    <button
                        key={option.type}
                        type="button"
                        data-attr={option['data-attr']}
                        onClick={() => onSelect(option.type, proceedFor[option.type])}
                        className="flex cursor-pointer flex-col gap-2 rounded-lg border border-primary bg-surface-primary p-3 text-left transition-colors hover:border-accent hover:bg-surface-secondary"
                    >
                        <div className="h-32 w-full overflow-hidden rounded-md bg-surface-secondary p-2">
                            {option.preview}
                        </div>
                        <div className="flex items-center gap-2">
                            <span className="text-lg text-accent">{option.icon}</span>
                            <span className="font-semibold text-primary">{option.label}</span>
                            {option.tag && (
                                <LemonTag type={option.tag === 'new' ? 'success' : 'warning'} size="small">
                                    {option.tag === 'new' ? 'New' : 'Beta'}
                                </LemonTag>
                            )}
                        </div>
                        <div className="text-xs text-secondary">{option.description}</div>
                    </button>
                ))}
            </div>
        </LemonModal>
    )
}
