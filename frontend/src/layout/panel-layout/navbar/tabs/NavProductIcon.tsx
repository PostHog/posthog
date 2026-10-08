import { FileSystemIconType, FileSystemImport } from '~/queries/schema/schema-general'

import { getCustomIcon } from '../../ProjectTree/customIconRegistry'
import { ProductIconWrapper, iconForType } from '../../ProjectTree/defaultTree'

export function NavProductIcon({ item }: { item: FileSystemImport }): JSX.Element {
    const CustomIcon = getCustomIcon(item.type, item.href)
    const iconType = item.iconType ?? (item.type as FileSystemIconType | undefined)
    return CustomIcon ? (
        <ProductIconWrapper type={iconType} colorOverride={item.iconColor}>
            <CustomIcon />
        </ProductIconWrapper>
    ) : (
        iconForType(iconType, item.iconColor)
    )
}
