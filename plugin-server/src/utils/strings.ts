export function sanitizeForUTF8(input: string): string {
    // the JS console truncates some logs...
    // when it does that it doesn't check if the output is valid UTF-8
    // and so it can truncate halfway through a UTF-16 pair 🤷
    // the simplest way to fix this is to convert to a buffer and back
    // annoyingly Node 20 has `toWellFormed` which might have been useful
    const buffer = Buffer.from(input)
    return buffer.toString()
}
