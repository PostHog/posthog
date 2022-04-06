import { DateTimePropertyTypeFormat, PropertyType, UnixTimestampPropertyTypeFormat } from '../../types'

// magic copied from https://stackoverflow.com/a/54930905
// allows candidate to be typed as any
// eslint-disable-next-line @typescript-eslint/explicit-module-boundary-types
export const isNumericString = (candidate: any): boolean => {
    return !(candidate instanceof Array) && candidate - parseFloat(candidate) + 1 >= 0
}

export const unixTimestampPropertyTypeFormatPatterns: Record<keyof typeof UnixTimestampPropertyTypeFormat, RegExp> = {
    UNIX_TIMESTAMP: /^\d{10}(\.\d*)?$/,
    UNIX_TIMESTAMP_MILLISECONDS: /^\d{13}$/,
}

export const dateTimePropertyTypeFormatPatterns: Record<keyof typeof DateTimePropertyTypeFormat, RegExp> = {
    DATE: /^\d{4}-\d{2}-\d{2}$/,
    ISO8601_DATE: /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?(?:\d{2})?)$/i,
    FULL_DATE: /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/,
    FULL_DATE_INCREASING: /^\d{2}-\d{2}-\d{4} \d{2}:\d{2}:\d{2}$/,
    WITH_SLASHES: /^\d{4}\/\d{2}\/\d{2} \d{2}:\d{2}:\d{2}$/,
    WITH_SLASHES_INCREASING: /^\d{2}\/\d{2}\/\d{4} \d{2}:\d{2}:\d{2}$/,
    // see https://datatracker.ietf.org/doc/html/rfc2822#section-3.3
    RFC_822:
        /^((mon|tue|wed|thu|fri|sat|sun), )?\d{2} (jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec) \d{4} \d{2}:\d{2}:\d{2}( [+|-]\d{4})?$/i,
}

export const detectPropertyDefinitionTypes = (value: unknown, key: string): PropertyType | null => {
    let propertyType: PropertyType | null = null

    /**
     * Auto-detecting unix timestamps is tricky. It's hard to know what is a big number or ID and what is a timestamp
     *
     * This tries to detect the most likely cases.
     *
     * * Numbers or Numeric Strings
     * * That are either ten digits (seconds since unix epoch), or 13 digits (milliseconds since unix epoch),
     * * or ten digits with numbers after the decimal place (whole seconds since unix epoch and fractions of a second)
     * * where the property key includes either time or timestamp
     *
     * ten digits of seconds since epoch runs between Sep 09 2001 and Nov 20th 2286
     *
     * These are some representations from a variety of programming languages
     *
     * Python
     * >>> datetime.now().timestamp()
     * 1641477529.234715
     *
     * Ruby
     * puts Time.now.to_i
     * 1641477692
     *
     * Node JS
     * console.log(Date.now())
     * 1641477753371
     *
     * Java
     * System.out.println(LocalDateTime.now().toEpochSecond(ZoneOffset.UTC));
     * 1641478115
     *
     * SQL Lite
     * select strftime('%s', 'now')
     * 1641478347
     */
    const detectUnixTimestamps = () => {
        Object.values(unixTimestampPropertyTypeFormatPatterns).find((pattern) => {
            if (
                (key.toLowerCase().includes('timestamp') || key.toLowerCase().includes('time')) &&
                String(value).match(pattern)
            ) {
                propertyType = PropertyType.DateTime
                return true
            }
        })
    }

    if (typeof value === 'number') {
        propertyType = PropertyType.Numeric

        detectUnixTimestamps()
    }

    if (typeof value === 'string') {
        propertyType = PropertyType.String

        if (isNumericString(value)) {
            propertyType = PropertyType.Numeric
        }

        Object.values(dateTimePropertyTypeFormatPatterns).find((pattern) => {
            if (value.match(pattern)) {
                propertyType = PropertyType.DateTime
                return true
            }
        })

        detectUnixTimestamps()
    }

    if (
        typeof value === 'boolean' ||
        (typeof value === 'string' && ['true', 'false'].includes(value.trim().toLowerCase()))
    ) {
        propertyType = PropertyType.Boolean
    }

    return propertyType
}
