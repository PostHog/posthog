// Remove punctuation and illegal characters
const sanitize = (string: string): string => {
    return string
        .toLowerCase()
        .replace(/[ ’–—―′¿'`~!@#$%^&*()_|+\-=?;:'",.<>\{\}\[\]\\\/]/gi, '-')
        .replace(/-+/g, '-')
        .replace(/^-+/, '')
        .replace(/-+$/, '')
}

// Generate a story id from a story kind and name
export const toId = (kind: string, name?: string): string => `${sanitize(kind)}${name ? `--${sanitize(name)}` : ''}`
