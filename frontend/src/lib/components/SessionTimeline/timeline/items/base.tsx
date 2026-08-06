export function BasePreview({
    name,
    description,
    descriptionTitle,
}: {
    name: React.ReactNode
    descriptionTitle?: string
    description?: React.ReactNode
}): JSX.Element {
    return (
        <div className="flex justify-between items-center">
            <span className="font-medium">{name}</span>
            {description && (
                <span className="text-secondary text-xs line-clamp-1 max-w-2/3 text-right" title={descriptionTitle}>
                    {description}
                </span>
            )}
        </div>
    )
}

const MAX_PREVIEW_TEXT_LENGTH = 300
const MIN_PREVIEW_TEXT_SECTION_LENGTH = 20
const PREFERRED_PRIMARY_TEXT_SHARE = 0.65

function truncateText(value: string, maxLength: number): string {
    if (maxLength <= 0) {
        return ''
    }

    if (value.length <= maxLength) {
        return value
    }

    if (maxLength === 1) {
        return '…'
    }

    return `${value.slice(0, maxLength - 1)}…`
}

export function truncatePreviewTexts({
    primaryText,
    secondaryText,
    maxTotalLength = MAX_PREVIEW_TEXT_LENGTH,
}: {
    primaryText: string
    secondaryText?: string
    maxTotalLength?: number
}): { primaryText: string; secondaryText?: string } {
    const normalizedSecondaryText = secondaryText ? secondaryText : undefined

    if (!normalizedSecondaryText) {
        return {
            primaryText: truncateText(primaryText, maxTotalLength),
        }
    }

    const totalLength = primaryText.length + normalizedSecondaryText.length
    if (totalLength <= maxTotalLength) {
        return {
            primaryText,
            secondaryText: normalizedSecondaryText,
        }
    }

    const minimumSectionLength = Math.min(MIN_PREVIEW_TEXT_SECTION_LENGTH, Math.floor(maxTotalLength / 2))

    let primaryBudget = Math.max(minimumSectionLength, Math.round(maxTotalLength * PREFERRED_PRIMARY_TEXT_SHARE))
    let secondaryBudget = maxTotalLength - primaryBudget

    if (secondaryBudget < minimumSectionLength) {
        secondaryBudget = minimumSectionLength
        primaryBudget = maxTotalLength - secondaryBudget
    }

    if (primaryBudget < minimumSectionLength) {
        primaryBudget = minimumSectionLength
        secondaryBudget = maxTotalLength - primaryBudget
    }

    if (primaryText.length < primaryBudget) {
        const extra = primaryBudget - primaryText.length
        primaryBudget = primaryText.length
        secondaryBudget = Math.min(maxTotalLength - primaryBudget, secondaryBudget + extra)
    }

    if (normalizedSecondaryText.length < secondaryBudget) {
        const extra = secondaryBudget - normalizedSecondaryText.length
        secondaryBudget = normalizedSecondaryText.length
        primaryBudget = Math.min(maxTotalLength - secondaryBudget, primaryBudget + extra)
    }

    return {
        primaryText: truncateText(primaryText, primaryBudget),
        secondaryText: truncateText(normalizedSecondaryText, secondaryBudget),
    }
}

export function StandardizedPreview({
    primaryText,
    secondaryText,
    secondaryMuted = true,
}: {
    primaryText: string
    secondaryText?: string
    secondaryMuted?: boolean
}): JSX.Element {
    const { primaryText: truncatedPrimaryText, secondaryText: truncatedSecondaryText } = truncatePreviewTexts({
        primaryText,
        secondaryText,
    })

    const primary = <span className="truncate block">{truncatedPrimaryText}</span>

    const secondary = (
        <span className={secondaryMuted ? 'text-tertiary truncate block' : 'truncate block'}>
            {truncatedSecondaryText}
        </span>
    )

    return (
        <div className="w-full min-w-0 pr-2 overflow-hidden">
            <div className="flex items-center min-w-0 overflow-hidden w-full">
                <div
                    className={`font-medium min-w-0 truncate ${truncatedSecondaryText ? 'max-w-[70%]' : 'w-full'}`}
                    title={truncatedPrimaryText !== primaryText ? primaryText : undefined}
                >
                    {primary}
                </div>
                {truncatedSecondaryText ? (
                    <>
                        <span aria-hidden className="text-tertiary text-[10px] leading-none shrink-0 mx-1">
                            •
                        </span>
                        <div
                            className="text-xs min-w-0 flex-1 truncate"
                            title={truncatedSecondaryText !== secondaryText ? secondaryText : undefined}
                        >
                            {secondary}
                        </div>
                    </>
                ) : null}
            </div>
        </div>
    )
}
