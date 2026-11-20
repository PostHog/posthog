export const HEDGEHOG_LIFETIME_SECONDS = 3 * 365.25 * 24 * 60 * 60

export function formatEstimateCount(count: number, maximumSignificantDigits = 3): string {
    if (count >= 1e12) {
        return 'over 1 trillion'
    }
    return new Intl.NumberFormat('en-US', {
        notation: 'compact',
        compactDisplay: 'long',
        maximumSignificantDigits,
    }).format(count)
}

export function hedgehogLifetimes(seconds: number): string {
    const lifetimes = seconds / HEDGEHOG_LIFETIME_SECONDS
    if (lifetimes < 0.01) {
        return 'Less than 0.01 hedgehog lifetimes'
    }
    const formatted = formatEstimateCount(lifetimes, 2)
    return `${formatted} hedgehog ${formatted === '1' ? 'lifetime' : 'lifetimes'}`
}
