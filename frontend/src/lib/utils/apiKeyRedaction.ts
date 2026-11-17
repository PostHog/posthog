// Personal API keys (phx_) and project secret API keys (phs_). The API returns the full value once,
// when a key is created or rolled. The SDK body scrubbing matches field names, and the field is `value`.
const API_KEY = /\b(ph[xs]_)[0-9A-Za-z]{20,}/g

export function redactApiKeys(body: unknown): unknown {
    return typeof body === 'string' ? body.replace(API_KEY, '$1redacted') : body
}
