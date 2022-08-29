import React from 'react'
import { findAllIndices } from 'lib/utils'

const STRING_INCLUDES_URL = new RegExp(
    '([a-zA-Z0-9]+://)?([a-zA-Z0-9_]+:[a-zA-Z0-9_]+@)?([a-zA-Z0-9.-]+\\.[A-Za-z]{2,4})(:[0-9]+)?(/.*)?'
)

export interface ParsedEntry {
    type: 'array' | 'object' | 'string'
    parsed: Array<any> | Record<string, any> | React.ReactNode
    size: number
    traceUrl?: React.ReactNode // first url in stack
}

// Parses single payload entry
//  - If url is detected in the string, shorten it and wrap with <a> tag
//  - If object is detected in string, parse it and make it pretty
//  - If array is detected in string, parse it and make it pretty
export function parseEntry(entry: string): ParsedEntry {
    // If entry is flanked by `"`'s, remove them.
    let rawEntry = entry.replace(/^"/, '').replace(/"$/, '')
    let traceUrl: React.ReactNode = null

    // Check if object or array
    try {
        const parsedObject = JSON.parse(rawEntry)
        const isArray = Array.isArray(parsedObject)
        return {
            type: isArray ? 'array' : 'object',
            parsed: parsedObject,
            size: isArray ? parsedObject.length : Object.keys(parsedObject).length,
        }
    } catch {
        /* Silently catch errors and continue to parse entry as string */
    }

    // Align all whitespace
    rawEntry = rawEntry.replace(/\\n/g, ' ').replace(/\s+/g, ' ')

    // Wrap urls with anchor tags
    const rawEntriesSplit = rawEntry.split(' ').map((splitEntry) => {
        if (STRING_INCLUDES_URL.test(rawEntry)) {
            // Parse the trace string
            // trace[] contains strings that looks like:
            // * ":123:456"
            // * "https://example.com/path/to/file.js:123:456"
            // * "https://example.com/path/to/file.js:123:456 End of object"
            // * "Login (https://example.com/path/to/file.js:123:456)"
            // * "https://example.com/path/to/file.js:123:456 https://example.com/path/to/file.js:123:456 https://example.com/path/to/file.js:123:456"
            // Note: there may be other formats too, but we only handle these ones now
            const splitString = rawEntry.split(/\s+/g)
            const urlIndices = findAllIndices(splitString, (s) => s.split(':').length >= 3)

            // URL doesn't exist here
            if (urlIndices.length === 0) {
                return rawEntry
            }

            let element = <></>
            splitString.forEach((splitPart, index) => {
                if (urlIndices.includes(index)) {
                    const url = splitPart.replace(/^\(/, '').replace(/\)$/, '') // remove flanking parentheses
                    let shortenedURL
                    const splitTrace = url.split(':')
                    const lineNumbers = splitTrace.slice(-2).join(':').split(/\s+/)[0]
                    const baseURL = splitTrace.slice(0, -2).join(':')
                    if (splitTrace.length >= 4) {
                        // Case with URL and line number
                        try {
                            const fileNameFromURL = new URL(baseURL).pathname.split('/').slice(-1)[0]
                            shortenedURL = `${fileNameFromURL}:${lineNumbers}`
                        } catch (e) {
                            // If we can't parse the URL, fall back to this line number
                            shortenedURL = `:${lineNumbers}`
                        }
                    } else if (splitTrace.length === 3) {
                        // Case with line number only
                        shortenedURL = `:${lineNumbers}`
                    }
                    const link = (
                        <a href={baseURL} target="_blank">
                            {shortenedURL}
                        </a>
                    )
                    element = (
                        <>
                            {element} {link}
                        </>
                    )
                    if (!traceUrl) {
                        traceUrl = link
                    }
                } else {
                    element = (
                        <>
                            {element} {splitPart}
                        </>
                    )
                }
            })
            return element
        }
        return <>{splitEntry}</>
    })

    return {
        parsed: rawEntriesSplit,
        type: 'string',
        size: -1,
        traceUrl,
    }
}
