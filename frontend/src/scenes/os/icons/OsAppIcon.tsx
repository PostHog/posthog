import './OsAppIcon.scss'

import { CSSProperties } from 'react'

import { cn } from 'lib/utils/css-classes'

import { getIconColor, iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { fileSystemTypes } from '~/products'

import type { OsApp } from '../store/osAppCatalog'

export type OsAppIconApp = Pick<OsApp, 'iconType' | 'iconColor'>

export interface OsAppIconProps {
    /** The app whose product icon and color the tile shows. Null for an OS item that is not an app. */
    app: OsAppIconApp | null
    /** `custom` leaves the size to `className`, for surfaces that size their icons with CSS. */
    size: 'small' | 'medium' | 'large' | 'custom'
    className?: string
    /** Drawn in place of the product icon, for OS items that are not products. */
    icon?: JSX.Element
    color?: string
}

const SIZE_CLASSES: Record<OsAppIconProps['size'], string> = {
    small: 'size-7',
    medium: 'size-11',
    large: 'size-16',
    custom: '',
}

/**
 * The product color of an app, or null for an app without one. The light variant is the saturated one, and
 * a white glyph needs it in both themes. Manifests name a file system type whose `iconType` carries the
 * color, so the lookup follows that type too.
 */
export function osAppIconColor(app: OsAppIconApp | null): string | null {
    if (!app) {
        return null
    }
    const [color] = getIconColor(app.iconType, app.iconColor)
    if (color !== 'currentColor') {
        return color
    }
    const resolvedType = (fileSystemTypes as Record<string, { iconType?: string } | undefined>)[app.iconType ?? '']
        ?.iconType
    const [resolvedColor] = resolvedType ? getIconColor(resolvedType) : [color]
    return resolvedColor !== 'currentColor' ? resolvedColor : null
}

export function OsAppIcon({ app, size, className, icon, color }: OsAppIconProps): JSX.Element {
    const tileColor = color ?? osAppIconColor(app)

    return (
        <span
            aria-hidden
            className={cn('OsAppIcon', SIZE_CLASSES[size], className)}
            // oxlint-disable-next-line react/forbid-dom-props
            style={tileColor ? ({ '--os-app-icon-color': tileColor } as CSSProperties) : undefined}
        >
            {icon ?? iconForType(app?.iconType)}
        </span>
    )
}
