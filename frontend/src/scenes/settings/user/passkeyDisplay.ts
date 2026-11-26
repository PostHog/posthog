export function getAuthenticatorTypeText(type: 'platform' | 'hardware' | 'hybrid' | 'unknown'): string {
    switch (type) {
        case 'hardware':
            return 'Hardware'
        case 'platform':
            return 'Platform'
        case 'hybrid':
            return 'Hybrid'
        default:
            return 'Unknown'
    }
}

export function getVerificationStatusText(verified: boolean, verifying: boolean): string {
    if (verifying) {
        return 'Verifying'
    }
    if (verified) {
        return 'Verified'
    }
    return 'Not verified'
}
