import { HogFunctionTemplate } from '../../types'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'alpha',
    type: 'transformation',
    id: 'template-url-normalization',
    name: 'URL Normalization',
    description:
        'Normalizes URLs by replacing dynamic path segments (containing numbers or capital letters) with :id placeholders. This helps group similar URLs together for analysis.',
    icon_url: '/static/hedgehog/reading-hog.png',
    category: ['Custom'],
    hog: `

// Function to normalize a path segment
fun normalizePathSegment(segment) {
    if (not match(segment, inputs.regex)) {
        return segment
    }
    return inputs.replaceWith
}

fun normalizePath(path, splitBy) {
    if (empty(path)) {
        return path
    }
    let segments := splitByString(splitBy, path)

    let normalizedSegments := []
    for (let segment in segments) {
        if (not empty(segment)) {
            let normalizedSegment := normalizePathSegment(segment)
            normalizedSegments := arrayPushBack(normalizedSegments, normalizedSegment)
        } else {
            normalizedSegments := arrayPushBack(normalizedSegments, segment)
        }
    }
    return arrayStringConcat(normalizedSegments, splitBy)
}

fun normalizeQueryString(queryString) {
    let params := splitByString('&', queryString)
    let normalizedParams := []
    for (let param in params) {
        if (not empty(param)) {
            let keyValue := splitByString('=', param, 2)
            print('keyValue', keyValue)
            if (length(keyValue) > 1) {
                let key := keyValue[1]
                let value := keyValue[2]

                if (match(value, inputs.regex)) {
                    value := inputs.replaceWith
                    normalizedParams := arrayPushBack(normalizedParams, concat(key, '=', value))
                } else {
                    normalizedParams := arrayPushBack(normalizedParams, param)
                }
            } else {
                normalizedParams := arrayPushBack(normalizedParams, param)
            }
        }
    }

    print('normalizedParams', normalizedParams)
    return arrayStringConcat(normalizedParams, '&')
}

fun normalizeHash(hash) {
    // Hash params are sometimes used as sub-urls
    // Remove query params from hash
    let hashParts := splitByString('?', hash, 2)
    let hashPath := hashParts[1]
    hashPath := normalizePath(hashPath, '/')

    // Now normalize it like a query string
    return normalizeQueryString(hashPath)
}

fun normalizeUrl(url) {
    if (empty(url) or typeof(url) != 'string') {
        return url
    }

    // Find positions (1-based)
    let hashIndex := position(url, '#')
    let queryIndex := position(url, '?')

    let main := url
    let query := ''
    let hash := ''

    // Split hash first, then query from main URL only
    if (hashIndex > 0) {
        main := substring(url, 1, hashIndex - 1)
        hash := substring(url, hashIndex + 1, length(url) - hashIndex + 1)
        
        // Check if main URL has query parameters (before the hash)
        let mainQueryIndex := position(main, '?')
        if (mainQueryIndex > 0) {
            let newMain := substring(main, 1, mainQueryIndex - 1)
            query := substring(main, mainQueryIndex + 1, length(main) - mainQueryIndex + 1)
            main := newMain
        }
    } else if (queryIndex > 0) {
        main := substring(url, 1, queryIndex - 1)
        query := substring(url, queryIndex + 1, length(url) - queryIndex + 1)
    }

    // Find protocol end (e.g., 'https://')
    let protoEnd := position(main, '//')
    let domainSlash := 0
    if (protoEnd > 0) {
        // Find first slash after protocol
        let afterProto := protoEnd + 2
        let rest := substring(main, afterProto, length(main) - afterProto + 1)
        let relSlash := position(rest, '/')
        if (relSlash > 0) {
            domainSlash := afterProto + relSlash - 1
        }
    }
    let domain := main
    let path := ''
    if (domainSlash > 0) {
        domain := substring(main, 1, domainSlash - 1)
        path := substring(main, domainSlash, length(main) - domainSlash + 1)
    }

    let normalizedPath := normalizePath(path, '/')
    let normalizedHash := (empty(hash) or inputs.removeHash) ? '' : normalizeHash(hash)
    let normalizedQuery := (empty(query) or inputs.removeQueryString) ? '' : normalizeQueryString(query)
    let result := concat(domain, normalizedPath)
    if (not empty(normalizedQuery)) {
        result := concat(result, '?', normalizedQuery)
    }
    if (not empty(normalizedHash)) {
        result := concat(result, '#', normalizedHash)
    }
    return result
}

// Create a copy of the event to modify
let normalizedEvent := event

// Process URL properties
let urlProperties := splitByString(',', inputs.urlProperties)
for (let propName in urlProperties) {
    propName := trim(propName)
    if (not empty(event.properties?.[propName])) {
        normalizedEvent.properties[propName] := normalizeUrl(event.properties[propName])
    }

    // Process $set and $set_once properties
    if (not empty(event.properties?.$set?.[propName])) {
        normalizedEvent.properties.$set[propName] := normalizeUrl(event.properties.$set[propName])
    }
    if (not empty(event.properties?.$set_once?.[propName])) {
        normalizedEvent.properties.$set_once[propName] := normalizeUrl(event.properties.$set_once[propName])
    }
}

return normalizedEvent
// NOTE: This template does not decode percent-encoded segments (e.g., %20 for space) due to Hog limitations.
    `,
    inputs_schema: [
        {
            key: 'removeHash',
            label: 'Remove hash parameter',
            type: 'boolean',
            description: 'Whether to remove the hash parameter in the normalized URL',
            default: true,
        },
        {
            key: 'removeQueryString',
            label: 'Remove query string',
            type: 'boolean',
            description: 'Whether to remove the query string in the normalized URL',
            default: true,
        },
        {
            key: 'replaceWith',
            label: 'Replace with token',
            type: 'string',
            description: 'The string to replace parts that look like a dynamic path segment. Defaults to :id',
            default: ':id',
        },
        {
            key: 'urlProperties',
            type: 'string',
            label: 'URL properties to normalize',
            description:
                'Comma-separated list of event properties to normalize. Can include both event properties and top-level event fields like distinct_id.',
            default: '$current_url, $referrer, $referring_domain',
            secret: false,
            required: true,
        },

        {
            key: 'regex',
            label: 'Regex',
            type: 'string',
            description:
                'The regex to use to match the dynamic path segment. The default value will match UUIDs and strings of 3 or more capital letters or numbers.',
            templating: false,
            default: '^([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|[A-Z0-9]{3,})$',
        },
    ],
}
