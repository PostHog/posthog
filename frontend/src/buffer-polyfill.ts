import { Buffer } from 'buffer'

// Make Buffer available globally for browser compatibility
if (typeof window !== 'undefined') {
    // @ts-expect-error
    window.Buffer = Buffer
    // @ts-expect-error
    window.global = window.global || window
    // @ts-expect-error
    window.global.Buffer = Buffer
}

if (typeof globalThis !== 'undefined') {
    // @ts-expect-error
    globalThis.Buffer = Buffer
}
