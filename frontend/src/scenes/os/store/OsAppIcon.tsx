import { cn } from 'lib/utils/css-classes'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'

import type { OsApp } from './osAppCatalog'

export interface OsAppIconProps {
    app: Pick<OsApp, 'iconType' | 'iconColor'>
    /** `custom` leaves the size to `className`, for surfaces that size their icons with CSS. */
    size: 'small' | 'medium' | 'large' | 'custom'
    className?: string
    /** Drawn in place of the product icon, for OS items that are not products. */
    icon?: JSX.Element
}

const SIZE_CLASSES: Record<OsAppIconProps['size'], string> = {
    small: 'size-7 rounded-md [&_svg]:size-4',
    medium: 'size-11 rounded-lg [&_svg]:size-6',
    large: 'size-16 rounded-xl [&_svg]:size-9',
    custom: '',
}

/** An app's product icon in its product color, on a tile. */
export function OsAppIcon({ app, size, className, icon }: OsAppIconProps): JSX.Element {
    return (
        <span
            aria-hidden
            className={cn(
                'group/colorful-product-icons colorful-product-icons-true inline-flex shrink-0 items-center justify-center border border-primary bg-surface-primary',
                SIZE_CLASSES[size],
                className
            )}
        >
            {icon ?? iconForType(app.iconType, app.iconColor)}
        </span>
    )
}
