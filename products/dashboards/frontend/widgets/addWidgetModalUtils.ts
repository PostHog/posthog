import { getDashboardWidgetPickerItem } from '../widget_types/catalog'

export type AddWidgetPayload = {
    widgetType: string
    config: Record<string, unknown>
}

export function getAddButtonLabel(selectedCount: number): string {
    if (selectedCount <= 1) {
        return 'Add widget'
    }
    return `Add ${selectedCount} widgets`
}

export function getAddWidgetDisabledReason(loading: boolean | undefined, selectedCount: number): string | undefined {
    if (loading) {
        return 'Adding widgets…'
    }
    if (selectedCount === 0) {
        return 'Select at least one widget type'
    }
    return undefined
}

/** Builds one tile per selected picker key: a widget type, or `<widget type>:<preset id>` for a preset card. */
export function buildAddWidgetPayloads(selectedKeys: Iterable<string>): AddWidgetPayload[] {
    const payloads: AddWidgetPayload[] = []

    for (const key of selectedKeys) {
        const item = getDashboardWidgetPickerItem(key)
        if (!item) {
            continue
        }
        payloads.push({ widgetType: item.widgetType, config: item.defaultConfig })
    }

    return payloads
}

export async function submitAddWidgetPayloads(
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

    // onAdd (dashboardLogic.addWidgetTiles) toasts and rethrows on failure — keep the modal open.
    await onAdd(payloads)
    onClose()
}
