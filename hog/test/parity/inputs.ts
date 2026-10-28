// Deterministic inputs for parity goldens. The recorder and the tests generate the same bytes from
// (generator, seed, size), so large inputs never need to be checked in.
export type Generator = 'ascii' | 'lines' | 'bytes'

export interface InputSpec {
    generator: Generator
    seed: number
    size: number
}

// xorshift32: tiny, fast and identical everywhere.
function random(seed: number): () => number {
    let state = seed >>> 0 || 1
    return () => {
        state ^= state << 13
        state >>>= 0
        state ^= state >>> 17
        state ^= state << 5
        state >>>= 0
        return state
    }
}

const LINE_WORDS = ['com.example.app.Model', 'getValue', 'setValue', 'onCreate', 'java.lang.String', 'int', 'void']

export function generateInput({ generator, seed, size }: InputSpec): Uint8Array {
    const next = random(seed)
    const out = new Uint8Array(size)
    if (generator === 'bytes') {
        for (let index = 0; index < size; index++) {
            out[index] = next() & 0xff
        }
        return out
    }
    if (generator === 'ascii') {
        for (let index = 0; index < size; index++) {
            out[index] = 32 + (next() % 95)
        }
        return out
    }
    // `lines`: ProGuard-like text, so compression finds long repeats like a real mapping.
    let index = 0
    while (index < size) {
        const word = LINE_WORDS[next() % LINE_WORDS.length]!
        const line = `    ${next() % 900}:${next() % 900}:${word} ${word}(${next() % 7}) -> ${String.fromCharCode(97 + (next() % 26))}\n`
        for (let char = 0; char < line.length && index < size; char++) {
            out[index++] = line.charCodeAt(char)
        }
    }
    return out
}
