export function createWildcardMatcher(pattern: string, wildcard: '*' | '%' = '*'): (value: string) => boolean {
    return (value) => {
        // Each state is a matched pattern prefix. Keeping all states avoids wildcard backtracking.
        const states = new Uint8Array(pattern.length + 1)
        states[0] = 1
        for (let index = 1; index <= pattern.length; index++) {
            states[index] = pattern[index - 1] === wildcard ? states[index - 1] : 0
        }

        // Index by UTF-16 code unit to retain non-Unicode RegExp literal semantics.
        for (let offset = 0; offset < value.length; offset++) {
            const character = value[offset]
            const wildcardAllowed =
                character !== '\n' && character !== '\r' && character !== '\u2028' && character !== '\u2029'
            let previous = states[0]
            states[0] = 0
            for (let index = 1; index <= pattern.length; index++) {
                const saved = states[index]
                states[index] =
                    pattern[index - 1] === wildcard
                        ? Number(Boolean(states[index - 1] || (saved && wildcardAllowed)))
                        : Number(Boolean(previous && pattern[index - 1] === character))
                previous = saved
            }
        }

        return Boolean(states[pattern.length])
    }
}
