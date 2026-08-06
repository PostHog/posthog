import './WordArt.scss'

import clsx from 'clsx'
import { useId } from 'react'

import { DEFAULT_WORD_ART_SIZE } from './wordArtPresets'

const ARCH_PATH_LENGTH = 465

function WordArtArched({ text, className }: { text: string; className?: string }): JSX.Element {
    const gradientId = useId()

    return (
        <svg viewBox="0 0 500 170" className={clsx('WordArt--arch-svg', className)} role="img" aria-label={text}>
            <defs>
                <linearGradient id={gradientId} x1="0" y1="0" x2="1" y2="0">
                    <stop offset="0%" stopColor="#7b2ff7" />
                    <stop offset="50%" stopColor="#f107a3" />
                    <stop offset="100%" stopColor="#ff8c37" />
                </linearGradient>
            </defs>
            <path id={`${gradientId}-path`} d="M 30 150 Q 250 30 470 150" fill="none" />
            <text fontSize={56} fontWeight={900} fill={`url(#${gradientId})`} stroke="#4a1772" strokeWidth={1}>
                <textPath
                    href={`#${gradientId}-path`}
                    startOffset="50%"
                    textAnchor="middle"
                    textLength={ARCH_PATH_LENGTH}
                    lengthAdjust="spacingAndGlyphs"
                >
                    {text}
                </textPath>
            </text>
        </svg>
    )
}

export function WordArtText({
    text,
    style,
    size = DEFAULT_WORD_ART_SIZE,
    className,
}: {
    text: string
    style: string
    size?: string
    className?: string
}): JSX.Element {
    const sizeClass = `WordArt--size-${size}`

    if (style === 'arch') {
        return <WordArtArched text={text} className={clsx(sizeClass, className)} />
    }

    return <span className={clsx('WordArt', `WordArt--${style}`, sizeClass, className)}>{text}</span>
}
