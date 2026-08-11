/** Compares a user-typed confirmation phrase against the expected one, ignoring case and surrounding whitespace. */
export function matchesConfirmationText(input: string, expected: string): boolean {
    return input.trim().toLowerCase() === expected.trim().toLowerCase()
}
