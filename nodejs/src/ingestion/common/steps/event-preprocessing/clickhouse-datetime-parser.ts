/**
 * ClickHouse DateTime Best Effort Parser
 *
 * A faithful JavaScript port of ClickHouse's parseDateTimeBestEffort logic.
 * Translated line-by-line from: ClickHouse/src/IO/parseDateTimeBestEffort.cpp
 *
 * ARCHITECTURE (mirrors ClickHouse's two-layer design):
 *
 * In ClickHouse, parsing happens in two layers:
 *
 * 1. Parser (parseDateTimeBestEffort.cpp):
 *    - Parses as much as it can from the input buffer
 *    - Returns success/failure for the parsing itself
 *    - Does NOT check if all input was consumed
 *
 * 2. Wrapper (FunctionsConversion.h:1464-1465):
 *    - Calls the parser
 *    - Then checks: if (!isAllRead(read_buffer)) parsed = false;
 *    - This rejects inputs like "2020-01-01garbage" where parsing succeeds but trailing data remains
 *
 * We mirror this structure:
 * - parseDateTimeBestEffort(): Layer 1 - returns { outcome, fullyConsumed }
 * - isValidClickHouseDateTime(): Layer 2 - combines both checks
 */

interface ParseResult {
    valid: true
    unixSeconds: number
    fractional: { value: number; digits: number }
}

interface ParseFailure {
    valid: false
}

type ParseOutcome = ParseResult | ParseFailure

/**
 * Internal result from the parser (Layer 1).
 * The wrapper (Layer 2) uses both fields to determine final validity.
 */
interface ParseInternalResult {
    /** Did parsing succeed? */
    outcome: ParseOutcome
    /** Was the entire input consumed? (false means trailing garbage like "2020-01-01xyz") */
    fullyConsumed: boolean
}

// Helper: isNumericASCII - from StringUtils.h line 88-94
function isNumericASCII(c: string): boolean {
    return c >= '0' && c <= '9'
}

// Helper: isAlphaASCII - from StringUtils.h line 83-86
function isAlphaASCII(c: string): boolean {
    return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z')
}

// Helper: isSymbolIn - from ReadHelpers.h line 501-514
function isSymbolIn(symbol: string, symbols: string | null): boolean {
    if (symbols === null) {
        return true
    }
    return symbols.includes(symbol)
}

// Helper: strncasecmp equivalent
function strncasecmp(a: string, b: string, n: number): number {
    const aLower = a.slice(0, n).toLowerCase()
    const bLower = b.slice(0, n).toLowerCase()
    if (aLower < bLower) {
        return -1
    }
    if (aLower > bLower) {
        return 1
    }
    return 0
}

/**
 * ReadBuffer simulation - tracks position in string
 */
class ReadBuffer {
    private s: string
    private pos: number

    constructor(s: string) {
        this.s = s
        this.pos = 0
    }

    eof(): boolean {
        return this.pos >= this.s.length
    }

    position(): string {
        return this.s[this.pos]
    }

    advance(): void {
        this.pos++
    }

    // checkChar - from ReadHelpers.h line 198-205
    checkChar(c: string): boolean {
        if (this.eof() || this.s[this.pos] !== c) {
            return false
        }
        this.pos++
        return true
    }
}

// readDigits - from parseDateTimeBestEffort.cpp line 25-35
function readDigits(buf: ReadBuffer, maxChars: number): number[] {
    const res: number[] = []
    while (!buf.eof() && isNumericASCII(buf.position()) && res.length < maxChars) {
        res.push(buf.position().charCodeAt(0) - 48) // '0' is 48
        buf.advance()
    }
    return res
}

// readAlpha - from parseDateTimeBestEffort.cpp line 37-47
function readAlpha(buf: ReadBuffer, maxChars: number): string {
    let res = ''
    while (!buf.eof() && isAlphaASCII(buf.position()) && res.length < maxChars) {
        res += buf.position()
        buf.advance()
    }
    return res
}

// readDecimalNumber - converts digit array to number
function readDecimalNumber(digits: number[], start: number, count: number): number {
    let res = 0
    for (let i = 0; i < count; i++) {
        res = res * 10 + digits[start + i]
    }
    return res
}

/**
 * Layer 1: Parser - faithful translation from parseDateTimeBestEffort.cpp
 *
 * Parses as much as it can and returns:
 * - outcome: did parsing succeed?
 * - fullyConsumed: was all input consumed?
 *
 * Note: This function does NOT reject trailing garbage - that's Layer 2's job.
 * For validation, use isValidClickHouseDateTime() which combines both checks.
 *
 * C++ template parameters mapped to our implementation:
 * - ReturnType: bool (tryParse variant, returns success/failure instead of throwing)
 * - is_us_style: passed as usStyle option (MM/DD vs DD/MM)
 * - strict: false (non-strict parsing allows timestamps, compact formats)
 * - is_64: true (DateTime64 support with fractional seconds)
 */
export function parseDateTimeBestEffort(
    input: string,
    options: { usStyle?: boolean; allowedDateDelimiters?: string | null } = {}
): ParseInternalResult {
    const { usStyle = false, allowedDateDelimiters = null } = options

    if (typeof input !== 'string') {
        return { outcome: { valid: false }, fullyConsumed: true }
    }

    const s = input.trim()
    if (s.length === 0) {
        return { outcome: { valid: false }, fullyConsumed: true }
    }

    const buf = new ReadBuffer(s)

    // Line 113-130: State variables
    let year = 0
    let month = 0
    let day_of_month = 0
    let hour = 0
    let minute = 0
    let second = 0

    let has_time = false

    let has_time_zone_offset = false
    let time_zone_offset_negative = false
    let time_zone_offset_hour = 0
    let time_zone_offset_minute = 0

    let is_am = false
    let is_pm = false

    let has_comma_between_date_and_time = false

    const fractional = { value: 0, digits: 0 }

    // Line 133-150: read_alpha_month lambda
    const read_alpha_month = (alpha: string): boolean => {
        if (strncasecmp(alpha, 'Jan', 3) === 0) {
            month = 1
        } else if (strncasecmp(alpha, 'Feb', 3) === 0) {
            month = 2
        } else if (strncasecmp(alpha, 'Mar', 3) === 0) {
            month = 3
        } else if (strncasecmp(alpha, 'Apr', 3) === 0) {
            month = 4
        } else if (strncasecmp(alpha, 'May', 3) === 0) {
            month = 5
        } else if (strncasecmp(alpha, 'Jun', 3) === 0) {
            month = 6
        } else if (strncasecmp(alpha, 'Jul', 3) === 0) {
            month = 7
        } else if (strncasecmp(alpha, 'Aug', 3) === 0) {
            month = 8
        } else if (strncasecmp(alpha, 'Sep', 3) === 0) {
            month = 9
        } else if (strncasecmp(alpha, 'Oct', 3) === 0) {
            month = 10
        } else if (strncasecmp(alpha, 'Nov', 3) === 0) {
            month = 11
        } else if (strncasecmp(alpha, 'Dec', 3) === 0) {
            month = 12
        } else {
            return false
        }
        return true
    }

    // Line 152-689: Main parsing loop
    while (!buf.eof()) {
        // Line 154-164: Check for comma between date and time
        if ((year && !has_time) || (!year && has_time)) {
            if (buf.position() === ',') {
                has_comma_between_date_and_time = true
                buf.advance()

                if (buf.eof()) {
                    break
                }
            }
        }

        // Line 166-168
        let digits: number[] = []
        let num_digits = 0

        // Line 170-500: Read digits if we don't have year or time yet
        if (!year || !has_time) {
            digits = readDigits(buf, 19) // sizeof(digits) in C++ is 19 for UInt64
            num_digits = digits.length

            // Line 174-189: 13 digits - unix timestamp with milliseconds
            if (num_digits === 13 && !year && !has_time) {
                const res = readDecimalNumber(digits, 0, 10)
                return {
                    outcome: {
                        valid: true,
                        unixSeconds: res,
                        fractional: { value: readDecimalNumber(digits, 10, 3), digits: 3 },
                    },
                    fullyConsumed: buf.eof(),
                }
            }

            // Line 190-204: 10 digits - unix timestamp
            if (num_digits === 10 && !year && !has_time) {
                const res = readDecimalNumber(digits, 0, 10)
                const frac = { value: 0, digits: 0 }
                if (!buf.eof() && buf.position() === '.') {
                    buf.advance()
                    const fracDigits = readDigits(buf, 19)
                    frac.digits = fracDigits.length
                    frac.value = readDecimalNumber(fracDigits, 0, fracDigits.length)
                }
                return {
                    outcome: { valid: true, unixSeconds: res, fractional: frac },
                    fullyConsumed: buf.eof(),
                }
            }

            // Line 205-218: 9 digits - unix timestamp
            if (num_digits === 9 && !year && !has_time) {
                const res = readDecimalNumber(digits, 0, 9)
                const frac = { value: 0, digits: 0 }
                if (!buf.eof() && buf.position() === '.') {
                    buf.advance()
                    const fracDigits = readDigits(buf, 19)
                    frac.digits = fracDigits.length
                    frac.value = readDecimalNumber(fracDigits, 0, fracDigits.length)
                }
                return {
                    outcome: { valid: true, unixSeconds: res, fractional: frac },
                    fullyConsumed: buf.eof(),
                }
            }

            // Line 220-234: 14 digits - YYYYMMDDhhmmss
            if (num_digits === 14 && !year && !has_time) {
                year = readDecimalNumber(digits, 0, 4)
                month = readDecimalNumber(digits, 4, 2)
                day_of_month = readDecimalNumber(digits, 6, 2)
                hour = readDecimalNumber(digits, 8, 2)
                minute = readDecimalNumber(digits, 10, 2)
                second = readDecimalNumber(digits, 12, 2)
                has_time = true
            }
            // Line 235-245: 8 digits - YYYYMMDD
            else if (num_digits === 8 && !year) {
                year = readDecimalNumber(digits, 0, 4)
                month = readDecimalNumber(digits, 4, 2)
                day_of_month = readDecimalNumber(digits, 6, 2)
            }
            // Line 246-268: 6 digits - YYYYMM or hhmmss
            else if (num_digits === 6) {
                if (!year && !month) {
                    year = readDecimalNumber(digits, 0, 4)
                    month = readDecimalNumber(digits, 4, 2)
                } else if (!has_time) {
                    hour = readDecimalNumber(digits, 0, 2)
                    minute = readDecimalNumber(digits, 2, 2)
                    second = readDecimalNumber(digits, 4, 2)
                    has_time = true
                } else {
                    return { outcome: { valid: false }, fullyConsumed: buf.eof() } // ambiguous
                }
            }
            // Line 269-330: 4 digits - YYYY with potential MM and DD
            else if (num_digits === 4 && !year) {
                year = readDecimalNumber(digits, 0, 4)

                if (!buf.eof()) {
                    const delimiter_after_year = buf.position()

                    // Line 284-286: Check for terminating characters
                    if (
                        delimiter_after_year.charCodeAt(0) < 0x20 ||
                        delimiter_after_year === ',' ||
                        delimiter_after_year === ';' ||
                        delimiter_after_year === "'" ||
                        delimiter_after_year === '"'
                    ) {
                        break
                    }

                    // Line 288-289: If month already set, continue
                    if (month) {
                        continue
                    }

                    // Line 291: Advance past delimiter
                    buf.advance()

                    // Line 293-305: Read month
                    digits = readDigits(buf, 19)
                    num_digits = digits.length

                    if (num_digits === 2) {
                        month = readDecimalNumber(digits, 0, 2)
                    } else if (num_digits === 1) {
                        month = readDecimalNumber(digits, 0, 1)
                    } else if (delimiter_after_year === ' ') {
                        continue
                    } else {
                        return { outcome: { valid: false }, fullyConsumed: buf.eof() }
                    }

                    // Line 307-323: Read day if same delimiter follows
                    if (!day_of_month && buf.checkChar(delimiter_after_year)) {
                        digits = readDigits(buf, 19)
                        num_digits = digits.length

                        if (num_digits === 2) {
                            day_of_month = readDecimalNumber(digits, 0, 2)
                        } else if (num_digits === 1) {
                            day_of_month = readDecimalNumber(digits, 0, 1)
                        } else if (delimiter_after_year === ' ') {
                            continue
                        } else {
                            return { outcome: { valid: false }, fullyConsumed: buf.eof() }
                        }
                    }

                    // Line 325-329: Check if delimiter is allowed
                    if (!isSymbolIn(delimiter_after_year, allowedDateDelimiters)) {
                        return { outcome: { valid: false }, fullyConsumed: buf.eof() }
                    }
                }
            }
            // Line 332-496: 1-2 digits
            else if (num_digits === 2 || num_digits === 1) {
                let hour_or_day_of_month_or_month = 0
                if (num_digits === 2) {
                    hour_or_day_of_month_or_month = readDecimalNumber(digits, 0, 2)
                } else {
                    hour_or_day_of_month_or_month = readDecimalNumber(digits, 0, 1)
                }

                // Line 353-387: Check for ':' - it's time
                if (buf.checkChar(':')) {
                    if (has_time) {
                        return { outcome: { valid: false }, fullyConsumed: buf.eof() } // time component duplicated
                    }

                    hour = hour_or_day_of_month_or_month
                    has_time = true

                    digits = readDigits(buf, 19)
                    num_digits = digits.length

                    if (num_digits === 2) {
                        minute = readDecimalNumber(digits, 0, 2)
                    } else if (num_digits === 1) {
                        minute = readDecimalNumber(digits, 0, 1)
                    } else {
                        return { outcome: { valid: false }, fullyConsumed: buf.eof() }
                    }

                    if (buf.checkChar(':')) {
                        digits = readDigits(buf, 19)
                        num_digits = digits.length

                        if (num_digits === 2) {
                            second = readDecimalNumber(digits, 0, 2)
                        } else if (num_digits === 1) {
                            second = readDecimalNumber(digits, 0, 1)
                        } else {
                            return { outcome: { valid: false }, fullyConsumed: buf.eof() }
                        }
                    }
                }
                // Line 388-392: Check for ',' after number when we have month
                else if (buf.checkChar(',')) {
                    if (month && !day_of_month) {
                        day_of_month = hour_or_day_of_month_or_month
                    }
                }
                // Line 393-481: Date separator - DD/MM/YYYY or MM/DD/YYYY
                else if (
                    !buf.eof() &&
                    isSymbolIn(buf.position(), allowedDateDelimiters) &&
                    (buf.checkChar('/') || buf.checkChar('.') || buf.checkChar('-'))
                ) {
                    // Line 397-401: Check for duplicates
                    if (day_of_month) {
                        return { outcome: { valid: false }, fullyConsumed: buf.eof() } // day_of_month duplicated
                    }
                    if (month) {
                        return { outcome: { valid: false }, fullyConsumed: buf.eof() } // month duplicated
                    }

                    // Line 403-451: US style vs non-US style
                    if (usStyle) {
                        // Line 405-415: US style - MM/DD/YYYY
                        month = hour_or_day_of_month_or_month
                        digits = readDigits(buf, 19)
                        num_digits = digits.length
                        if (num_digits === 2) {
                            day_of_month = readDecimalNumber(digits, 0, 2)
                        } else if (num_digits === 1) {
                            day_of_month = readDecimalNumber(digits, 0, 1)
                        } else {
                            return { outcome: { valid: false }, fullyConsumed: buf.eof() }
                        }
                    } else {
                        // Line 418-451: Non-US style - DD/MM/YYYY
                        day_of_month = hour_or_day_of_month_or_month

                        digits = readDigits(buf, 19)
                        num_digits = digits.length

                        if (num_digits === 2) {
                            month = readDecimalNumber(digits, 0, 2)
                        } else if (num_digits === 1) {
                            month = readDecimalNumber(digits, 0, 1)
                        } else if (num_digits === 0) {
                            // Line 427-445: Month in alphabetical form
                            const alpha = readAlpha(buf, 9) // longest month: September
                            const num_alpha = alpha.length

                            if (num_alpha < 3) {
                                return { outcome: { valid: false }, fullyConsumed: buf.eof() }
                            }

                            if (!read_alpha_month(alpha)) {
                                return { outcome: { valid: false }, fullyConsumed: buf.eof() }
                            }
                        } else {
                            return { outcome: { valid: false }, fullyConsumed: buf.eof() }
                        }
                    }

                    // Line 453-454: Swap if month > 12
                    if (month > 12) {
                        ;[month, day_of_month] = [day_of_month, month]
                    }

                    // Line 456-480: Read year if another separator follows
                    if (
                        !buf.eof() &&
                        isSymbolIn(buf.position(), allowedDateDelimiters) &&
                        (buf.checkChar('/') || buf.checkChar('.') || buf.checkChar('-'))
                    ) {
                        if (year) {
                            return { outcome: { valid: false }, fullyConsumed: buf.eof() } // year duplicated
                        }

                        digits = readDigits(buf, 19)
                        num_digits = digits.length

                        if (num_digits === 4) {
                            year = readDecimalNumber(digits, 0, 4)
                        } else if (num_digits === 2) {
                            year = readDecimalNumber(digits, 0, 2)
                            // Line 470-473: Two-digit year interpretation
                            if (year >= 70) {
                                year += 1900
                            } else {
                                year += 2000
                            }
                        } else {
                            return { outcome: { valid: false }, fullyConsumed: buf.eof() }
                        }
                    }
                }
                // Line 482-495: No separator - it's day_of_month or hour
                else {
                    if (day_of_month) {
                        hour = hour_or_day_of_month_or_month
                    } else {
                        day_of_month = hour_or_day_of_month_or_month
                    }
                }
            }
            // Line 497-499: Other number of digits is invalid
            else if (num_digits !== 0) {
                return { outcome: { valid: false }, fullyConsumed: buf.eof() }
            }
        }

        // Line 502-688: Handle non-digit characters
        if (num_digits === 0) {
            const c = buf.position()

            // Line 506-512: Space or 'T' separator
            if (c === ' ' || (c === 'T' && year && !has_time)) {
                buf.advance()
            }
            // Line 513-517: 'Z' timezone marker
            else if (c === 'Z') {
                buf.advance()
                has_time_zone_offset = true
            }
            // Line 518-541: '.' fractional seconds
            else if (c === '.') {
                if (!has_time) {
                    return { outcome: { valid: false }, fullyConsumed: buf.eof() }
                }

                buf.advance()
                const fracDigits = readDigits(buf, 19)
                // Line 531: Limit digits to avoid overflow (18 digits for Int64)
                const limitedDigits = Math.min(18, fracDigits.length)
                fractional.digits = limitedDigits
                fractional.value = readDecimalNumber(fracDigits, 0, limitedDigits)
            }
            // Line 542-604: '+' or '-' timezone offset or time
            else if (c === '+' || c === '-') {
                buf.advance()
                digits = readDigits(buf, 19)
                num_digits = digits.length

                // Line 547-554: 6 digits after +/- with date but no time = hhmmss
                if (num_digits === 6 && !has_time && year && month && day_of_month) {
                    hour = readDecimalNumber(digits, 0, 2)
                    minute = readDecimalNumber(digits, 2, 2)
                    second = readDecimalNumber(digits, 4, 2)
                    has_time = true
                } else {
                    // Line 555-603: Timezone offset
                    has_time_zone_offset = true
                    if (c === '-') {
                        time_zone_offset_negative = true
                    }

                    if (num_digits === 4) {
                        time_zone_offset_hour = readDecimalNumber(digits, 0, 2)
                        time_zone_offset_minute = readDecimalNumber(digits, 2, 2)
                    } else if (num_digits === 3) {
                        time_zone_offset_hour = readDecimalNumber(digits, 0, 1)
                        time_zone_offset_minute = readDecimalNumber(digits, 1, 2)
                    } else if (num_digits === 2) {
                        time_zone_offset_hour = readDecimalNumber(digits, 0, 2)
                    } else if (num_digits === 1) {
                        time_zone_offset_hour = readDecimalNumber(digits, 0, 1)
                    } else {
                        return { outcome: { valid: false }, fullyConsumed: buf.eof() }
                    }

                    // Line 586-603: Check for ':' and read minutes
                    if (num_digits < 3 && buf.checkChar(':')) {
                        digits = readDigits(buf, 19)
                        num_digits = digits.length

                        if (num_digits === 2) {
                            time_zone_offset_minute = readDecimalNumber(digits, 0, 2)
                        } else if (num_digits === 1) {
                            time_zone_offset_minute = readDecimalNumber(digits, 0, 1)
                        } else {
                            return { outcome: { valid: false }, fullyConsumed: buf.eof() }
                        }
                    }
                }
            }
            // Line 606-687: Alphabetical characters
            else {
                const alpha = readAlpha(buf, 3)
                const num_alpha = alpha.length

                // Line 612-615: No alpha chars - break
                if (num_alpha === 0) {
                    break
                }

                // Line 616-619: 1 char - invalid
                if (num_alpha === 1) {
                    return { outcome: { valid: false }, fullyConsumed: buf.eof() }
                }

                // Line 620-637: 2 chars - AM/PM
                if (num_alpha === 2) {
                    if (alpha[1] === 'M' || alpha[1] === 'm') {
                        if (alpha[0] === 'A' || alpha[0] === 'a') {
                            is_am = true
                        } else if (alpha[0] === 'P' || alpha[0] === 'p') {
                            is_pm = true
                        } else {
                            return { outcome: { valid: false }, fullyConsumed: buf.eof() }
                        }
                    } else {
                        return { outcome: { valid: false }, fullyConsumed: buf.eof() }
                    }
                }
                // Line 638-684: 3 chars - month, timezone, or day of week
                else if (num_alpha === 3) {
                    let has_day_of_week = false

                    if (read_alpha_month(alpha)) {
                        // month set by read_alpha_month
                    } else if (strncasecmp(alpha, 'UTC', 3) === 0) {
                        has_time_zone_offset = true
                    } else if (strncasecmp(alpha, 'GMT', 3) === 0) {
                        has_time_zone_offset = true
                    } else if (strncasecmp(alpha, 'MSK', 3) === 0) {
                        has_time_zone_offset = true
                        time_zone_offset_hour = 3
                    } else if (strncasecmp(alpha, 'MSD', 3) === 0) {
                        has_time_zone_offset = true
                        time_zone_offset_hour = 4
                    } else if (strncasecmp(alpha, 'Mon', 3) === 0) {
                        has_day_of_week = true
                    } else if (strncasecmp(alpha, 'Tue', 3) === 0) {
                        has_day_of_week = true
                    } else if (strncasecmp(alpha, 'Wed', 3) === 0) {
                        has_day_of_week = true
                    } else if (strncasecmp(alpha, 'Thu', 3) === 0) {
                        has_day_of_week = true
                    } else if (strncasecmp(alpha, 'Fri', 3) === 0) {
                        has_day_of_week = true
                    } else if (strncasecmp(alpha, 'Sat', 3) === 0) {
                        has_day_of_week = true
                    } else if (strncasecmp(alpha, 'Sun', 3) === 0) {
                        has_day_of_week = true
                    } else {
                        return { outcome: { valid: false }, fullyConsumed: buf.eof() }
                    }

                    // Line 678-679: Skip rest of alphabetical word
                    while (!buf.eof() && isAlphaASCII(buf.position())) {
                        buf.advance()
                    }

                    // Line 681-683: For RFC 2822, day of week is followed by comma
                    if (has_day_of_week) {
                        buf.checkChar(',')
                    }
                } else {
                    return { outcome: { valid: false }, fullyConsumed: buf.eof() }
                }
            }
        }
    }

    // Line 691-693: Comma between date and time requires both to be complete
    if (has_comma_between_date_and_time && (!has_time || !year || !month || !day_of_month)) {
        return { outcome: { valid: false }, fullyConsumed: buf.eof() }
    }

    // Line 695-697: Must have parsed something
    if (!year && !month && !day_of_month && !has_time) {
        return { outcome: { valid: false }, fullyConsumed: buf.eof() }
    }

    // Line 699-703: Default day_of_month to 1
    if (!day_of_month) {
        day_of_month = 1
    }

    // Line 706-710: Default month to 1
    if (!month) {
        month = 1
    }

    // Line 713-727: Default year to current year or previous year
    if (!year) {
        const now = new Date()
        const currYear = now.getFullYear()
        const currMonth = now.getMonth() + 1
        const currDay = now.getDate()

        // If the date (month, day) is not greater than today, use current year
        // Otherwise use previous year (for syslog format parsing)
        if (month < currMonth || (month === currMonth && day_of_month <= currDay)) {
            year = currYear
        } else {
            year = currYear - 1
        }
    }

    // Line 729-749: Date validation
    const is_leap_year = year % 400 === 0 || (year % 100 !== 0 && year % 4 === 0)

    const check_date = (is_leap: boolean, m: number, d: number): boolean => {
        if ((m === 1 || m === 3 || m === 5 || m === 7 || m === 8 || m === 10 || m === 12) && d >= 1 && d <= 31) {
            return true
        }
        if (m === 2 && ((is_leap && d >= 1 && d <= 29) || (!is_leap && d >= 1 && d <= 28))) {
            return true
        }
        if ((m === 4 || m === 6 || m === 9 || m === 11) && d >= 1 && d <= 30) {
            return true
        }
        return false
    }

    if (!check_date(is_leap_year, month, day_of_month)) {
        return { outcome: { valid: false }, fullyConsumed: buf.eof() }
    }

    // Line 751-755: AM/PM adjustment
    if (is_am && hour === 12) {
        hour = 0
    }
    if (is_pm && hour < 12) {
        hour += 12
    }

    // Line 757-786: Build timestamp
    let date: Date
    if (has_time_zone_offset) {
        date = new Date(Date.UTC(year, month - 1, day_of_month, hour, minute, second))
        const offsetMs = (time_zone_offset_hour * 60 + time_zone_offset_minute) * 60 * 1000
        if (time_zone_offset_negative) {
            date = new Date(date.getTime() + offsetMs)
        } else {
            date = new Date(date.getTime() - offsetMs)
        }
    } else {
        date = new Date(year, month - 1, day_of_month, hour, minute, second)
    }

    return {
        outcome: {
            valid: true,
            unixSeconds: Math.floor(date.getTime() / 1000),
            fractional,
        },
        fullyConsumed: buf.eof(),
    }
}

/**
 * Layer 2: Wrapper that mirrors FunctionsConversion.h
 *
 * Checks if a value will be successfully parsed by ClickHouse's
 * parseDateTime64BestEffortOrNull function.
 *
 * Combines two checks (just like ClickHouse):
 * 1. Did parsing succeed? (from parseDateTimeBestEffort)
 * 2. Was all input consumed? (mirrors: if (!isAllRead(read_buffer)) parsed = false)
 *
 * Example: "2020-01-01" -> true (valid, fully consumed)
 * Example: "2020-01-01xyz" -> false (valid parse, but "xyz" left over)
 * Example: "garbage" -> false (invalid parse)
 */
export function isValidClickHouseDateTime(value: unknown): boolean {
    if (typeof value === 'number') {
        return true
    }
    if (typeof value !== 'string') {
        return false
    }
    const { outcome, fullyConsumed } = parseDateTimeBestEffort(value)

    // FunctionsConversion.h line 1464-1465:
    // if (!isAllRead(read_buffer)) parsed = false;
    if (!fullyConsumed) {
        return false
    }

    return outcome.valid
}
