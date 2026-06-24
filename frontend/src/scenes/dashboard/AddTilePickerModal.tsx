import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconCursorClick, IconGraph, IconGridMasonry, IconLetter } from '@posthog/icons'

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
    'data-attr': string
}

/** A small fake trend chart so the user can picture an insight tile. */
function InsightPreview(): JSX.Element {
    const bars = ['h-3', 'h-6', 'h-4', 'h-9', 'h-7', 'h-12', 'h-10']
    return (
        <div className="flex h-full items-end justify-center gap-1 px-2 pb-1">
            {bars.map((height, index) => (
                <div key={index} className={`w-3 rounded-t-sm bg-accent ${height}`} />
            ))}
        </div>
    )
}

/** Sample rendered text so the user can picture a text card. */
function TextCardPreview(): JSX.Element {
    return (
        <div className="flex h-full flex-col justify-center gap-1 px-3 text-left">
            <div className="text-sm font-semibold text-primary">Q2 launch goals</div>
            <div className="text-xs text-secondary">
                Track weekly active users and conversion as we roll out the new onboarding flow.
            </div>
        </div>
    )
}

/** A non-interactive mock of a button tile. */
function ButtonPreview(): JSX.Element {
    return (
        <div className="flex h-full items-center justify-center">
            <span className="rounded bg-accent px-3 py-1.5 text-sm font-medium text-white">Read the docs →</span>
        </div>
    )
}

/** A small fake metric widget. */
function WidgetPreview(): JSX.Element {
    return (
        <div className="flex h-full flex-col items-center justify-center gap-0.5">
            <div className="text-2xl font-bold text-primary">1,234</div>
            <div className="text-xs text-secondary">Weekly active users</div>
            <div className="text-xs font-medium text-success">▲ 12%</div>
        </div>
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
            description: 'Drop in a ready-made widget from across PostHog.',
            icon: <IconGridMasonry />,
            preview: <WidgetPreview />,
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
            description="Pick what you'd like to add. Each preview shows roughly how it looks on the dashboard."
            width={720}
        >
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                {options.map((option) => (
                    <button
                        key={option.type}
                        type="button"
                        data-attr={option['data-attr']}
                        onClick={() => onSelect(option.type, proceedFor[option.type])}
                        className="flex flex-col gap-2 rounded-lg border border-primary bg-surface-primary p-3 text-left transition-colors hover:border-accent hover:bg-surface-secondary"
                    >
                        <div className="h-24 w-full overflow-hidden rounded-md bg-surface-secondary">
                            {option.preview}
                        </div>
                        <div className="flex items-center gap-2">
                            <span className="text-lg text-accent">{option.icon}</span>
                            <span className="font-semibold text-primary">{option.label}</span>
                        </div>
                        <div className="text-xs text-secondary">{option.description}</div>
                    </button>
                ))}
            </div>
        </LemonModal>
    )
}
