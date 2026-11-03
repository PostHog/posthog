// jsdom has no TextDecoder or TextEncoder. Browsers and Node.js have both.
const util = require('util')
globalThis.TextDecoder ??= util.TextDecoder
globalThis.TextEncoder ??= util.TextEncoder
