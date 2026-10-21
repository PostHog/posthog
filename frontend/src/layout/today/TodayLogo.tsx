import { Avatar, AvatarFallback, AvatarImage } from '@posthog/quill'

import { lettermarkColorIndex } from 'lib/lemon-ui/Lettermark/Lettermark'
import { backendAssetUrl } from 'lib/utils/apiHost'

/** quill's smallest avatar is 20px, so the tile and the menu row sizes override it. */
const SIZE_CLASSES = {
    tile: 'size-7 text-xs',
    trigger: undefined,
    row: 'size-4 text-[8px]',
} as const

export interface TodayLogoProps {
    name: string
    mediaId: string | null | undefined
    /** The entity ID that picks the fallback's lettermark color, or null for a neutral fallback. */
    colorSeed: number | string | null
    size: keyof typeof SIZE_CLASSES
}

/** An uploaded org or project logo, or its first letter. */
export function TodayLogo({ name, mediaId, colorSeed, size }: TodayLogoProps): JSX.Element {
    const color = colorSeed !== null ? lettermarkColorIndex(colorSeed) : null
    return (
        <Avatar size="xs" className={SIZE_CLASSES[size]}>
            {mediaId && <AvatarImage src={backendAssetUrl(`/uploaded_media/${mediaId}`)} alt="" />}
            <AvatarFallback
                className="font-semibold"
                // The palette is 16 theme-independent pairs in base.scss.
                style={
                    color
                        ? { backgroundColor: `var(--lettermark-${color}-bg)`, color: `var(--lettermark-${color}-text)` }
                        : undefined
                }
            >
                {name ? String.fromCodePoint(name.codePointAt(0)!).toLocaleUpperCase() : '?'}
            </AvatarFallback>
        </Avatar>
    )
}
