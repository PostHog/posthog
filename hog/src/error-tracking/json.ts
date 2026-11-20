const strictUtf8 = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true })

// serde_json::from_slice rejects invalid UTF-8 and treats a BOM as an unexpected character.
export function decodeUtf8(bytes: Uint8Array): string {
    return strictUtf8.decode(bytes)
}

// serde_json without `preserve_order` stores objects in a BTreeMap, so output keys are sorted by
// their UTF-8 bytes.
export function compareUtf8(a: string, b: string): number {
    return Buffer.compare(Buffer.from(a, 'utf8'), Buffer.from(b, 'utf8'))
}

// serde_json escapes the same characters as JSON.stringify for strings without lone surrogates.
export function writeString(value: string): string {
    return JSON.stringify(value)
}
