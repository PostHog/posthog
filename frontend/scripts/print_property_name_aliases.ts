import { KEY_MAPPING } from 'lib/taxonomy'

// Creates PROPERTY_NAME_ALIASES in posthog/api/property_definition.py
// eslint-disable-next-line no-console
console.log(
    JSON.stringify(
        Object.fromEntries(
            Array.from(Object.entries(KEY_MAPPING.event))
                .map(([key, value]) => [key, value.label])
                .filter(([key, label]) => {
                    if (!key) {
                        return false
                    }
                    if (!label || label.includes('deprecated')) {
                        return false
                    }

                    const keyLower = key.toLowerCase()
                    const labelLower = label.toLowerCase()

                    if (keyLower.includes(labelLower)) {
                        return false
                    }

                    const keyLowerNoSpecial = keyLower.replace(/[$_]+/g, ' ')
                    const labelWords = labelLower.split(/\s+/)

                    return !labelWords.every((word) => keyLowerNoSpecial.includes(word))
                })
                .sort()
        ),
        null,
        4
    )
)
