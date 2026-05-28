import { useActions, useValues } from 'kea'
import { Fragment } from 'react'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { isReadOnly } from 'lib/readOnlyGuard'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'

import {
    DASHBOARD_WIDGET_CATALOG,
    type DashboardWidgetCatalogEntry,
    type DashboardWidgetCatalogKey,
} from '../widget_types/catalog'
import { ADD_WIDGET_MODAL_WIDTH } from './constants'
import { DASHBOARD_WIDGET_PREVIEWS } from './previews/widgetPreviews'
import { WidgetTypePickerCard } from './WidgetTypePickerCard'

export type AddWidgetPayload = {
    widgetType: string
    config: Record<string, unknown>
}

type AddWidgetModalProps = {
    isOpen: boolean
    onClose: () => void
    loading?: boolean
    onAdd: (payloads: AddWidgetPayload[]) => Promise<void>
}

type DashboardWidgetCatalogGroup = {
    groupId: string
    groupLabel: string
    widgets: Array<{
        widgetType: DashboardWidgetCatalogKey
        entry: DashboardWidgetCatalogEntry
    }>
}

function getAddButtonLabel(selectedCount: number): string {
    if (selectedCount <= 1) {
        return 'Add widget'
    }
    return `Add ${selectedCount} widgets`
}

function getAddWidgetDisabledReason(loading: boolean | undefined, selectedCount: number): string | undefined {
    if (loading) {
        return 'Adding widgets…'
    }
    if (isReadOnly()) {
        return 'Read-only mode is on — allow writes temporarily to add widgets'
    }
    if (selectedCount === 0) {
        return 'Select at least one widget type'
    }
    return undefined
}

function getDashboardWidgetCatalogGroups(): DashboardWidgetCatalogGroup[] {
    const groupsById = new Map<string, DashboardWidgetCatalogGroup>()
    const groupOrder: string[] = []

    for (const widgetType of Object.keys(DASHBOARD_WIDGET_CATALOG) as DashboardWidgetCatalogKey[]) {
        const entry = DASHBOARD_WIDGET_CATALOG[widgetType]
        let group = groupsById.get(entry.groupId)

        if (!group) {
            group = { groupId: entry.groupId, groupLabel: entry.groupLabel, widgets: [] }
            groupsById.set(entry.groupId, group)
            groupOrder.push(entry.groupId)
        }

        group.widgets.push({ widgetType, entry })
    }

    return groupOrder.map((groupId) => groupsById.get(groupId)!)
}

const DASHBOARD_WIDGET_CATALOG_GROUPS = getDashboardWidgetCatalogGroups()

function buildAddWidgetPayloads(selectedTypes: Iterable<string>): AddWidgetPayload[] {
    const payloads: AddWidgetPayload[] = []

    for (const widgetType of selectedTypes) {
        const catalogEntry = DASHBOARD_WIDGET_CATALOG[widgetType as DashboardWidgetCatalogKey]
        if (!catalogEntry) {
            continue
        }
        payloads.push({ widgetType, config: catalogEntry.defaultConfig })
    }

    return payloads
}

async function submitAddWidgetPayloads(
    selectedTypes: Set<string>,
    onAdd: (payloads: AddWidgetPayload[]) => Promise<void>,
    onClose: () => void
): Promise<void> {
    if (selectedTypes.size === 0) {
        return
    }

    const payloads = buildAddWidgetPayloads(selectedTypes)
    if (payloads.length === 0) {
        return
    }

    try {
        await onAdd(payloads)
        onClose()
    } catch {
        // caller handles toast
    }
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
            width={ADD_WIDGET_MODAL_WIDTH}
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
