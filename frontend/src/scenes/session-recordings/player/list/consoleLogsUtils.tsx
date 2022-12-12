import { Link } from 'lib/components/Link'
import React from 'react'
import { RecordingConsoleLog, RecordingTimeMixinType, RRWebRecordingConsoleLogPayload } from '~/types'
import { capitalizeFirstLetter } from 'lib/utils'
import { ConsoleDetails, ConsoleDetailsProps } from 'scenes/session-recordings/player/list/ConsoleDetails'
import md5 from 'md5'

const STRING_INCLUDES_URL = new RegExp(
    '([a-zA-Z0-9]+://)?([a-zA-Z0-9_]+:[a-zA-Z0-9_]+@)?([a-zA-Z0-9.-]+\\.[A-Za-z]{2,4})(:[0-9]+)?(/.*)?'
)

export interface ParsedEntry {
    type: 'array' | 'object' | 'string'
    parsed: Array<any> | Record<string, any> | React.ReactNode
    rawString: string
    size: number
    traceUrl?: React.ReactNode // first url in stack
}

// Parses single payload entry
//  - If url is detected in the string, shorten it and wrap with <a> tag
//  - If object is detected in string, parse it and make it pretty
//  - If array is detected in string, parse it and make it pretty
export function parseEntry(entry?: string): ParsedEntry {
    if (!entry?.replace(/\s+/g, '')?.trim()) {
        return {
            type: 'string',
            parsed: null,
            size: 0,
            rawString: '',
        }
    }
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
            rawString: rawEntry,
            size: isArray ? parsedObject.length : Object.keys(parsedObject).length,
        }
    } catch {
        /* Silently catch errors and continue to parse entry as string */
    }

    // Align all whitespace
    rawEntry = rawEntry.replace(/\\n/g, '\n\t').replace(/\s+/g, ' ')

    // Wrap urls with anchor tags
    const finalStringBuilder: React.ReactElement[] = []
    rawEntry.split(/(\s+)/g).forEach((splitEntry) => {
        if (STRING_INCLUDES_URL.test(splitEntry) && splitEntry.split(':').length >= 3) {
            // Parse the trace string
            // trace[] contains strings that looks like:
            // * ":123:456"
            // * "https://example.com/path/to/file.js:123:456"
            // * "https://example.com/path/to/file.js:123:456 End of object"
            // * "Login (https://example.com/path/to/file.js:123:456)"
            // * "https://example.com/path/to/file.js:123:456 https://example.com/path/to/file.js:123:456 https://example.com/path/to/file.js:123:456"
            // Note: there may be other formats too, but we only handle these ones now

            const url = splitEntry.replace(/^\(/, '').replace(/\)$/, '') // remove flanking parentheses
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
                <Link to={baseURL} target="_blank">
                    {shortenedURL}
                </Link>
            )
            if (!traceUrl) {
                traceUrl = link
            }
            finalStringBuilder.push(<>{link}</>)
            return
        }
        finalStringBuilder.push(<>{splitEntry}</>)
    })

    return {
        parsed: (
            <>
                {finalStringBuilder.map((s, i) => (
                    <React.Fragment key={i}>{s}</React.Fragment>
                ))}
            </>
        ),
        rawString: rawEntry,
        type: 'string',
        size: -1,
        traceUrl,
    }
}

// Parses a rrweb console log payload into something the frontend likes
export function parseConsoleLogPayload(
    payload: RRWebRecordingConsoleLogPayload
): Omit<RecordingConsoleLog, keyof RecordingTimeMixinType> {
    const { level, payload: content, trace } = payload

    // Parse each string entry in content and trace
    const contentFiltered = Array.isArray(content) ? content?.filter((entry): entry is string => !!entry) ?? [] : []
    const traceFiltered = trace?.filter((entry): entry is string => !!entry) ?? []
    const parsedEntries = contentFiltered.map((entry) => parseEntry(entry))
    const parsedTrace = traceFiltered.map((entry) => parseEntry(entry))

    // Create a preview and full version of logs
    const previewContent = parsedEntries
        .map(({ type, size, parsed }) => {
            if (['array', 'object'].includes(type)) {
                return `${capitalizeFirstLetter(type)} (${size})`
            }
            return parsed
        })
        .flat()
    const fullContent = [
        ...parsedEntries.map(({ parsed, type }, idx) => {
            if (['array', 'object'].includes(type)) {
                return <ConsoleDetails json={parsed as ConsoleDetailsProps['json']} key={idx} />
            }
            return parsed
        }),
        ...parsedTrace.map(({ parsed }) => parsed),
    ].flat()
    const traceContent = parsedTrace.map(({ traceUrl }) => traceUrl).filter((traceUrl) => !!traceUrl)

    const parsedPayload = contentFiltered
        .map((item) => (item && item.startsWith('"') && item.endsWith('"') ? item.slice(1, -1) : item))
        .join(' ')

    return {
        parsedPayload,
        previewContent,
        fullContent,
        traceContent,
        rawString: parsedEntries.map(({ rawString }) => rawString).join(' '),
        count: 1,
        hash: md5(parsedPayload),
        level,
    }
}
