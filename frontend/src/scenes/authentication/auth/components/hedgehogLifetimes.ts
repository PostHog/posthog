export const HEDGEHOG_LIFETIME_SECONDS = 3 * 365.25 * 24 * 60 * 60

export function hedgehogLifetimes(seconds: number): string {
    const lifetimes = seconds / HEDGEHOG_LIFETIME_SECONDS
    if (lifetimes < 0.01) {
        return 'Less than 0.01 hedgehog lifetimes'
    }
    const formatted = new Intl.NumberFormat('en-US', {
        notation: 'compact',
        compactDisplay: 'long',
        maximumSignificantDigits: 2,
    }).format(lifetimes)
    return `${formatted} hedgehog ${formatted === '1' ? 'lifetime' : 'lifetimes'}`
}
