import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { FileSystemIconType, FileSystemImport } from '~/queries/schema/schema-general'

/** The product's static icon. The row shows counts at its end, so the icon carries no badge. */
export function TodayProductIcon({ item }: { item: FileSystemImport }): JSX.Element {
    return iconForType(item.iconType ?? (item.type as FileSystemIconType | undefined), item.iconColor)
}
