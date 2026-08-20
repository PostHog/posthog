// Email clients and manual entry can wrap the emailed code in whitespace or invisible characters
// (zero-width family, word joiner, BOM, soft hyphen) or group it as "123-456". Fold compatibility
// digits (e.g. fullwidth) to ASCII and drop that noise so a pasted code matches the server's 6 digits.
const CODE_NOISE_RE = /[\s\u200b-\u200d\u2060\ufeff\u00ad-]/g

export function normalizeVerificationCode(code: string): string {
    return (code ?? '').normalize('NFKC').replace(CODE_NOISE_RE, '')
}

export function isValidVerificationCode(code: string): boolean {
    return /^\d{6}$/.test(code)
}
