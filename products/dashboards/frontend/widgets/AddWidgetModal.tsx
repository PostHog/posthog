import { useActions, useValues } from 'kea'
import { Fragment } from 'react'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'

import {
    DASHBOARD_WIDGET_CATALOG_GROUPS,
    DASHBOARD_WIDGET_PREVIEWS,
    type DashboardWidgetCatalogEntry,
    type DashboardWidgetCatalogKey,
} from '../widget_types/catalog'
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
    const WidgetPreview = DASHBOARD_WIDGET_PREVIEWS[widgetType as keyof typeof DASHBOARD_WIDGET_PREVIEWS]

    function handleSelect(): void {
        onToggleWidgetType(widgetType)
    }

    return (
        <WidgetTypePickerCard
            label={entry.label}
            description={entry.description}
            selected={selected}
            preview={WidgetPreview ? <WidgetPreview /> : <div />}
            onSelect={handleSelect}
        />
    )
}

export function AddWidgetModal({ isOpen, onClose, loading, onAdd }: AddWidgetModalProps): JSX.Element {
    const { addWidgetSelectedTypes } = useValues(dashboardLogic)
    const { toggleAddWidgetSelectedType } = useActions(dashboardLogic)
    const selectedTypes = new Set(addWidgetSelectedTypes)

    const selectedCount = selectedTypes.size

    function handleToggleWidgetType(widgetType: string): void {
        toggleAddWidgetSelectedType(widgetType)
    }

    function handleAddWidgets(): void {
        void submitAddWidgetPayloads(selectedTypes, onAdd, onClose)
    }

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={onClose}
            title="Add widget"
            description="Bring context from your different PostHog products into one dashboard."
            width={960}
            footer={
                <>
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
                    className="grid grid-cols-1 @min-[36rem]/add-widget-modal:grid-cols-2 gap-x-3 gap-y-4"
                    aria-label="Widget types"
                >
                    {DASHBOARD_WIDGET_CATALOG_GROUPS.map((group, groupIndex) => (
                        <Fragment key={group.groupId}>
                            {groupIndex > 0 ? <LemonDivider className="col-span-full my-0" /> : null}
                            <h5 className="col-span-full mx-0 my-0">{group.groupLabel}</h5>
                            {group.widgets.map(({ widgetType, entry }) => (
                                <AddWidgetCatalogPicker
                                    key={widgetType}
                                    widgetType={widgetType}
                                    entry={entry}
                                    selected={selectedTypes.has(widgetType)}
                                    onToggleWidgetType={handleToggleWidgetType}
                                />
                            ))}
                        </Fragment>
                    ))}
                </div>
            </div>
        </LemonModal>
    )
}
