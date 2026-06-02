import type { DashboardWidgetEditModalProps } from './registry'

export type WidgetEditModalTileMetadataProps = Pick<
    DashboardWidgetEditModalProps,
    'name' | 'description' | 'defaultTitle' | 'onSaveMetadata'
>

export function getWidgetEditModalTileDefaults(props: Pick<DashboardWidgetEditModalProps, 'name' | 'description'>): {
    tileName: string
    tileDescription: string
} {
    return {
        tileName: props.name ?? '',
        tileDescription: props.description ?? '',
    }
}

export async function saveWidgetTileMetadataAfterConfig(
    props: WidgetEditModalTileMetadataProps,
    tileName: string,
    tileDescription: string
): Promise<void> {
    if (!props.onSaveMetadata) {
        return
    }

    const trimmedName = tileName.trim()
    const trimmedDescription = tileDescription.trim()
    const nameChanged = trimmedName !== (props.name ?? '').trim()
    const descriptionChanged = trimmedDescription !== (props.description ?? '').trim()

    const metadata: { name?: string; description?: string } = {}
    if (nameChanged) {
        metadata.name = trimmedName === (props.defaultTitle ?? 'Untitled').trim() ? '' : trimmedName
    }
    if (descriptionChanged) {
        metadata.description = trimmedDescription
    }
    if (Object.keys(metadata).length > 0) {
        await props.onSaveMetadata(metadata)
    }
}
