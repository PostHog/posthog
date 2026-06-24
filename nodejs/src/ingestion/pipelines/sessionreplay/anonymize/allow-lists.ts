/** Case-insensitive allow lists of text words and URL path segments kept verbatim by the scrubbers. */

function hasUpperAscii(s: string): boolean {
    for (let i = 0; i < s.length; i++) {
        const code = s.charCodeAt(i)
        if (code >= 0x41 && code <= 0x5a) {
            return true
        }
    }
    return false
}

function asciiLowercase(s: string): string {
    let out = ''
    for (let i = 0; i < s.length; i++) {
        const code = s.charCodeAt(i)
        out += code >= 0x41 && code <= 0x5a ? String.fromCharCode(code + 0x20) : s[i]
    }
    return out
}

export class AllowLists {
    private readonly text: Set<string>
    private readonly url: Set<string>

    constructor(text: Iterable<string>, url: Iterable<string>) {
        this.text = new Set<string>()
        for (const word of text) {
            this.text.add(asciiLowercase(word))
        }
        this.url = new Set<string>()
        for (const segment of url) {
            this.url.add(asciiLowercase(segment))
        }
    }

    public textContains(word: string): boolean {
        // Fast path: an already-lowercase word needs no allocation.
        return this.text.has(hasUpperAscii(word) ? asciiLowercase(word) : word)
    }

    public urlContains(segment: string): boolean {
        return this.url.has(hasUpperAscii(segment) ? asciiLowercase(segment) : segment)
    }
}
