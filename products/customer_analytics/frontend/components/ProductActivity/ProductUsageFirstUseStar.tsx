import { DotMatrixSymbol } from 'lib/components/DotMatrix/DotMatrixSymbol'

export function ProductUsageFirstUseStar({
    className,
    color = 'currentColor',
    label,
}: {
    className?: string
    color?: string
    label?: string
}): JSX.Element {
    return (
        <svg
            className={className}
            width="17"
            height="17"
            viewBox="0 0 17 17"
            role={label ? 'img' : undefined}
            aria-label={label}
            aria-hidden={label ? undefined : true}
        >
            <DotMatrixSymbol value={1} thresholds={[1]} color={color} firstUse />
        </svg>
    )
}
