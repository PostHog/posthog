import type { DashboardWidgetEditModalProps } from './registry'

export type WidgetEditModalTileMetadataProps = Pick<
    DashboardWidgetEditModalProps,
    'name' | 'description' | 'defaultTitle'
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

export type WidgetTileMetadataPatch = {
    name?: string
    description?: string
}

export function buildWidgetTileMetadataPatch(
    props: WidgetEditModalTileMetadataProps,
    tileName: string,
    tileDescription: string
): WidgetTileMetadataPatch {
    const trimmedName = tileName.trim()
    const trimmedDescription = tileDescription.trim()
    const nameChanged = trimmedName !== (props.name ?? '').trim()
    const descriptionChanged = trimmedDescription !== (props.description ?? '').trim()

    const metadata: WidgetTileMetadataPatch = {}
    if (nameChanged) {
        metadata.name = trimmedName === (props.defaultTitle ?? 'Untitled').trim() ? '' : trimmedName
    }
    if (descriptionChanged) {
        metadata.description = trimmedDescription
    }
    return metadata
}
