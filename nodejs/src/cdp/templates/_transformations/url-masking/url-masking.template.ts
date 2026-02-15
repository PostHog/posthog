import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'beta',
    type: 'transformation',
    id: 'template-url-masking',
    name: 'URL Parameter Masking',
    description: 'Masks sensitive information in URL parameters (query strings) of specified properties',
    icon_url: '/static/hedgehog/builder-hog-01.png',
    category: ['Custom'],
    code_language: 'hog',
    code: `
// Function to check if parameter matches any mask pattern
fun isParameterInList(paramName, paramsString) {
    let paramsList := splitByString(',', paramsString)
    for (let pattern in paramsList) {
        if (lower(paramName) =~ lower(trim(pattern))) {
            return true
        }
    }
    return false
}

// Function to mask URL parameters
fun maskURLParameters(url, paramsToMask, maskValue) {
    // If URL is empty or not a string, return as is
    if (empty(url) or typeof(url) != 'string') {
        return url
    }

    try {
        // Split URL into base and query string
        let parts := splitByString('?', url, 2)
        if (length(parts) < 2) {
            return url
        }
        
        let baseUrl := parts[1]
        let queryString := parts[2]
        
        // Handle malformed URLs that start with ?
        if (empty(baseUrl)) {
            return url
        }
        
        // Split query string into parameters
        let params := splitByString('&', queryString)
        let maskedParams := []
        
        // Process each parameter
        for (let param in params) {
            if (not empty(param)) {
                let keyValue := splitByString('=', param, 2)
                let paramName := keyValue[1]
                
                // Handle parameters without values (e.g., ?key&foo=bar)
                if (length(keyValue) < 2) {
                    if (isParameterInList(paramName, paramsToMask)) {
                        maskedParams := arrayPushBack(maskedParams, concat(paramName, '=', maskValue))
                    } else {
                        maskedParams := arrayPushBack(maskedParams, paramName)
                    }
                } else {
                    if (isParameterInList(paramName, paramsToMask)) {
                        maskedParams := arrayPushBack(maskedParams, concat(paramName, '=', maskValue))
                    } else {
                        maskedParams := arrayPushBack(maskedParams, param)
                    }
                }
            }
        }
        
        // Reconstruct URL with masked parameters
        return concat(baseUrl, '?', arrayStringConcat(maskedParams, '&'))
    } catch (error) {
        print('Error masking URL parameters:', error)
        return url
    }
}

// Create a copy of the event to modify
let maskedEvent := event

// Process each URL property
for (let propName, paramsToMask in inputs.urlProperties) {
    if (not empty(event.properties?.[propName])) {
        maskedEvent.properties[propName] := maskURLParameters(
            event.properties[propName],
            paramsToMask,
            inputs.maskWith
        )
    }
}

return maskedEvent
    `,
    inputs_schema: [
        {
            key: 'urlProperties',
            type: 'dictionary',
            label: 'URL Properties to Mask',
            description:
                "Map of event properties containing URLs and their parameters to mask. Example: {'$current_url': 'email, password'}",
            default: {
                $current_url: 'email, password, token',
                $referrer: 'email, password, token',
            },
            secret: false,
            required: true,
        },
        {
            key: 'maskWith',
            type: 'string',
            label: 'Mask Value',
            description: 'The value to replace sensitive parameters with',
            default: '[REDACTED]',
            secret: false,
            required: true,
        },
    ],
}
