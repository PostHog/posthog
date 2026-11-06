// A JSON string, which is skipped, or a JSON number literal.
const JSON_TOKEN = /"(?:[^"\\]|\\.)*"|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?/g
const DECIMAL = /^(-?)(\d+)(?:\.(\d+))?(?:[eE]([+-]?\d+))?$/

/** The exact decimal value of a number literal as sign, significant digits and exponent, so equal values compare equal. */
function canonicalDecimal(literal: string): string {
    const match = DECIMAL.exec(literal)
    if (!match) {
        return literal
    }
    const [, sign, integer, fraction = '', exponent = '0'] = match
    let digits = (integer + fraction).replace(/^0+/, '')
    let power = Number(exponent) - fraction.length
    while (digits.endsWith('0')) {
        digits = digits.slice(0, -1)
        power += 1
    }
    return digits === '' ? '0' : `${sign}${digits}e${power}`
}

function losesPrecision(literal: string): boolean {
    const parsed = Number(literal)
    return !Number.isFinite(parsed) || canonicalDecimal(literal) !== canonicalDecimal(String(parsed))
}

/** Whether `JSON.parse` would change any number in this JSON text, by rounding it or turning it into null. */
export function hasLossyNumber(json: string): boolean {
    for (const [token] of json.matchAll(JSON_TOKEN)) {
        if (!token.startsWith('"') && losesPrecision(token)) {
            return true
        }
    }
    return false
}
