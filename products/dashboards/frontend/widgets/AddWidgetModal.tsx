import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { Fragment } from 'react'

import { IconChevronDown, IconChevronRight, IconLightBulb } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { Link } from 'lib/lemon-ui/Link'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { teamLogic } from 'scenes/teamLogic'

import { ProductKey } from '~/queries/schema/schema-general'

import {
    DASHBOARD_WIDGET_CATALOG_GROUPS,
    DASHBOARD_WIDGET_PREVIEWS,
    type DashboardWidgetCatalogEntry,
    type DashboardWidgetCatalogKey,
    getDashboardWidgetGroupIcon,
    getDashboardWidgetGroupProductIntro,
} from '../widget_types/catalog'
import { isWidgetAvailabilityRequirementMet } from '../widget_types/widgetAvailability'
import {
    type AddWidgetPayload,
    getAddButtonLabel,
    getAddWidgetDisabledReason,
    submitAddWidgetPayloads,
} from './addWidgetModalUtils'
import { WidgetTypePickerCard } from './WidgetTypePickerCard'

export type { AddWidgetPayload }

type AddWidgetModalProps = {
    isOpen: boolean
    onClose: () => void
    loading?: boolean
    onAdd: (payloads: AddWidgetPayload[]) => Promise<void>
}

type AddWidgetCatalogPickerProps = {
    widgetType: DashboardWidgetCatalogKey
    entry: DashboardWidgetCatalogEntry
    selected: boolean
    onToggleWidgetType: (widgetType: string) => void
}

function AddWidgetCatalogPicker({
    widgetType,
    entry,
    selected,
    onToggleWidgetType,
}: AddWidgetCatalogPickerProps): JSX.Element {
    const WidgetPreview = DASHBOARD_WIDGET_PREVIEWS[widgetType]

    function handleSelect(): void {
        onToggleWidgetType(widgetType)
    }

    return (
        <WidgetTypePickerCard
            label={entry.label}
            badge={entry.badge}
            description={entry.description}
            selected={selected}
            preview={WidgetPreview ? <WidgetPreview /> : <div />}
            onSelect={handleSelect}
        />
    )
}

export function AddWidgetModal({ isOpen, onClose, loading, onAdd }: AddWidgetModalProps): JSX.Element {
    const { addWidgetSelectedTypes, addWidgetCollapsedGroups } = useValues(dashboardLogic)
    const { toggleAddWidgetSelectedType, toggleAddWidgetCollapsedGroup } = useActions(dashboardLogic)
    const { currentTeam } = useValues(teamLogic)
    const selectedTypes = new Set(addWidgetSelectedTypes)
    const collapsedGroups = new Set(addWidgetCollapsedGroups)

    const selectedCount = selectedTypes.size

    function handleToggleWidgetType(widgetType: string): void {
        toggleAddWidgetSelectedType(widgetType)
    }

    function handleAddWidgets(): void {
        void submitAddWidgetPayloads(selectedTypes, onAdd, onClose)
    }

    function handleFeedbackClicked(): void {
        posthog.capture('dashboard add widget modal - feedback clicked')
        onClose()
    }

    function handleProductIntroClicked(productType: ProductKey): void {
        posthog.capture('dashboard add widget modal - product intro clicked', { product_type: productType })
    }

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={onClose}
            title="Add widget"
            description="Bring context from your different PostHog products into one dashboard."
            width={1200}
            footer={
                <>
                    <LemonButton
                        type="tertiary"
                        size="small"
                        onClick={handleFeedbackClicked}
                        data-attr="dashboard-add-widget-feedback"
                    >
                        Missing a widget? Let us know
                    </LemonButton>
                    <div className="flex-1" />
                    <LemonButton type="secondary" onClick={onClose}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        loading={loading}
                        disabledReason={getAddWidgetDisabledReason(loading, selectedCount)}
                        onClick={handleAddWidgets}
                    >
                        {getAddButtonLabel(selectedCount)}
                    </LemonButton>
                </>
            }
        >
            <div className="@container/add-widget-modal">
                <div
                    className="grid grid-cols-1 @min-[56rem]/add-widget-modal:grid-cols-2 gap-x-3 gap-y-4"
                    aria-label="Widget types"
                >
                    {DASHBOARD_WIDGET_CATALOG_GROUPS.map((group, groupIndex) => {
                        const productIntro = getDashboardWidgetGroupProductIntro(group.groupId)
                        // Nudge only when the product's setup requirement (a project setting) is unmet.
                        const showProductIntro =
                            !!productIntro && !isWidgetAvailabilityRequirementMet(productIntro.requirement, currentTeam)
                        const GroupIcon = getDashboardWidgetGroupIcon(group.groupId)
                        const isCollapsed = collapsedGroups.has(group.groupId)

                        return (
                            <Fragment key={group.groupId}>
                                {groupIndex > 0 ? <LemonDivider className="col-span-full my-0" /> : null}
                                <div
                                    role="button"
                                    tabIndex={0}
                                    aria-expanded={!isCollapsed}
                                    onClick={() => toggleAddWidgetCollapsedGroup(group.groupId)}
                                    onKeyDown={(e) => {
                                        if (e.key === 'Enter' || e.key === ' ') {
                                            e.preventDefault()
                                            toggleAddWidgetCollapsedGroup(group.groupId)
                                        }
                                    }}
                                    className={clsx(
                                        'col-span-full flex flex-wrap items-center gap-x-3 gap-y-1 rounded px-3 py-2 cursor-pointer',
                                        'focus:outline-none focus-visible:ring-2 focus-visible:ring-accent',
                                        showProductIntro ? 'bg-accent-highlight-secondary' : 'bg-surface-secondary'
                                    )}
                                >
                                    <h5 className="m-0 flex shrink-0 items-center gap-1.5">
                                        {isCollapsed ? (
                                            <IconChevronRight className="shrink-0 text-base text-secondary" />
                                        ) : (
                                            <IconChevronDown className="shrink-0 text-base text-secondary" />
                                        )}
                                        {GroupIcon ? <GroupIcon className="text-base text-secondary" /> : null}
                                        {group.groupLabel}
                                    </h5>
                                    {showProductIntro && productIntro ? (
                                        <span className="flex items-start gap-1.5 text-xs text-secondary">
                                            <IconLightBulb className="mt-0.5 shrink-0 text-sm text-accent" />
                                            <span>
                                                {productIntro.valueProp}{' '}
                                                <Link
                                                    to={productIntro.docsHref}
                                                    target="_blank"
                                                    onClick={(e) => {
                                                        e.stopPropagation()
                                                        handleProductIntroClicked(productIntro.productKey)
                                                    }}
                                                >
                                                    {productIntro.ctaLabel}
                                                </Link>
                                            </span>
                                        </span>
                                    ) : null}
                                </div>
                                {!isCollapsed &&
                                    group.widgets.map(({ widgetType, entry }) => (
                                        <AddWidgetCatalogPicker
                                            key={widgetType}
                                            widgetType={widgetType}
                                            entry={entry}
                                            selected={selectedTypes.has(widgetType)}
                                            onToggleWidgetType={handleToggleWidgetType}
                                        />
                                    ))}
                            </Fragment>
                        )
                    })}
                </div>
            </div>
        </LemonModal>
    )
}
