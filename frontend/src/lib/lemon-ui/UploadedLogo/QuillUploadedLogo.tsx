import { Avatar, AvatarFallback, AvatarImage, cn } from '@posthog/quill'

import { lettermarkColorIndex } from '../Lettermark/Lettermark'

// quill's avatar sizes stop at 20px, so each logo size sets its own dimensions.
const SIZE_CLASSES = {
    xsmall: 'size-4 text-xxs',
    small: 'size-5 text-xxs',
    medium: 'size-6 text-xs',
    xlarge: 'size-16 text-2xl',
} as const

export interface QuillUploadedLogoProps {
    name: string
    entityId: number | string
    /** The uploaded image, or null for a lettermark. */
    imageSrc: string | null
    size: keyof typeof SIZE_CLASSES
    outlinedLettermark?: boolean
}

export function QuillUploadedLogo({
    name,
    entityId,
    imageSrc,
    size,
    outlinedLettermark,
}: QuillUploadedLogoProps): JSX.Element {
    const color = lettermarkColorIndex(entityId)
    const initial = name ? String.fromCodePoint(name.codePointAt(0)!).toLocaleUpperCase() : '?'

    return (
        <Avatar size="xs" className={cn(SIZE_CLASSES[size], outlinedLettermark && !imageSrc && 'bg-transparent')}>
            {imageSrc && <AvatarImage src={imageSrc} alt="Uploaded logo" className="object-cover" />}
            <AvatarFallback
                className={cn('font-semibold', outlinedLettermark && 'border border-dashed')}
                // The palette is 16 theme-independent pairs in base.scss.
                // eslint-disable-next-line react/forbid-dom-props
                style={
                    outlinedLettermark
                        ? { color: `var(--lettermark-${color}-bg)`, borderColor: `var(--lettermark-${color}-bg)` }
                        : { backgroundColor: `var(--lettermark-${color}-bg)`, color: `var(--lettermark-${color}-text)` }
                }
            >
                {initial}
            </AvatarFallback>
        </Avatar>
    )
}
