import { FileSystemIconType, FileSystemImport } from '~/queries/schema/schema-general'

import { iconForType } from '../../ProjectTree/defaultTree'

export function NavProductIcon({ item }: { item: FileSystemImport }): JSX.Element {
    const iconType = item.iconType ?? (item.type as FileSystemIconType | undefined)
    return iconForType(iconType, item.iconColor)
}
