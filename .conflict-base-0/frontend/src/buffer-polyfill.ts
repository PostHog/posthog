import { Buffer } from 'buffer'

// Make Buffer available globally for browser compatibility
if (typeof window !== 'undefined') {
    window.Buffer = Buffer
    window.global = window.global || window
    window.global.Buffer = Buffer
}

if (typeof globalThis !== 'undefined') {
    globalThis.Buffer = Buffer
}
