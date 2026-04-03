import { LemonSelectOptions } from '@posthog/lemon-ui'

type VerifiedFilterOption = 'all' | 'verified' | 'unverified'

export const verifiedOptions: LemonSelectOptions<VerifiedFilterOption> = [
    { value: 'all', label: 'All' },
    { value: 'verified', label: 'Verified only' },
    { value: 'unverified', label: 'Unverified only' },
]

export function verifiedFilterValue(verified: boolean | undefined): VerifiedFilterOption {
    if (verified === true) {
        return 'verified'
    }
    if (verified === false) {
        return 'unverified'
    }
    return 'all'
}

export function verifiedFilterFromOption(option: VerifiedFilterOption): boolean | undefined {
    if (option === 'verified') {
        return true
    }
    if (option === 'unverified') {
        return false
    }
    return undefined
}
