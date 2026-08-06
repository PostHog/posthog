/**
 * the JS console truncates some logs...
 * and we may truncate them during processing
 * JS strings are UTF-16 and the string truncation is (sort-of) UTF-8
 * some characters are represented by two "characters" in JS (surrogate pairs)
 * so the string can be truncated halfway through a "character"
 * in UTF-8 these are invalid and can cause errors in processing
 * the simplest way to fix this is to convert to a buffer and back
 * TODO: if we upgrade TS then we can use Node 20's `toWellFormed` avoiding this "hack"
 */
export function sanitizeForUTF8(input: string): string {
    return Buffer.from(input).toString()
}
