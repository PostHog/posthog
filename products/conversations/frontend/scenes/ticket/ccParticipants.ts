import { isEmail } from 'lib/utils/url'

export interface CcParticipantsResult {
    participants: string[]
    invalid: string[]
    alreadyReceiving: string[]
}

export function normalizeCcParticipants(
    addresses: string[],
    alwaysReceiving: (string | null | undefined)[]
): CcParticipantsResult {
    const excluded = new Set(
        alwaysReceiving.filter((address): address is string => !!address).map((a) => a.toLowerCase())
    )
    const result: CcParticipantsResult = { participants: [], invalid: [], alreadyReceiving: [] }
    for (const raw of addresses) {
        const address = raw.trim().toLowerCase()
        if (!address) {
            continue
        }
        if (!isEmail(address, { requireTLD: true })) {
            result.invalid.push(raw.trim())
        } else if (excluded.has(address)) {
            result.alreadyReceiving.push(address)
        } else if (!result.participants.includes(address)) {
            result.participants.push(address)
        }
    }
    return result
}

export function ccParticipantsEqual(a: readonly string[], b: readonly string[]): boolean {
    return JSON.stringify([...a].sort()) === JSON.stringify([...b].sort())
}
