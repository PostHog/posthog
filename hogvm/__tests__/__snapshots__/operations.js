function like (str, pattern) { return __like(str, pattern, false) }
function jsonStringify (value, spacing) {
    function convert(x, marked) {
        if (!marked) {
            marked = new Set()
        }
        if (typeof x === 'object' && x !== null) {
            if (marked.has(x)) {
                return null
            }
            marked.add(x)
            try {
                if (x instanceof Map) {
                    const obj = {}
                    x.forEach((value, key) => {
                        obj[convert(key, marked)] = convert(value, marked)
                    })
                    return obj
                }
                if (Array.isArray(x)) {
                    return x.map((v) => convert(v, marked))
                }
                if (__isHogDateTime(x) || __isHogDate(x) || __isHogError(x)) {
                    return x
                }
                if (typeof x === 'function') {
                    return `fn<${x.name || 'lambda'}(${x.length})>`
                }
                const obj = {}
                for (const key in x) {
                    obj[key] = convert(x[key], marked)
                }
                return obj
            } finally {
                marked.delete(x)
            }
        }
        return x
    }
    if (spacing && typeof spacing === 'number' && spacing > 0) {
        return JSON.stringify(convert(value), null, spacing)
    }
    return JSON.stringify(convert(value))
}
function concat (...args) { return args.map((arg) => (arg === null ? '' : __STLToString(arg))).join('') }
function match (str, pattern) { return new RegExp(pattern).test(str) }
function print (...args) { console.log(...args.map(__printHogStringOutput)) }
function toUUID (value) { return __STLToString(value) }
function toInt(value) {
    if (__isHogDateTime(value)) {
        return Math.floor(value.dt);
    } else if (__isHogDate(value)) {
        const date = new Date(Date.UTC(value.year, value.month - 1, value.day));
        const epoch = new Date(Date.UTC(1970, 0, 1));
        const diffInDays = Math.floor((date - epoch) / (1000 * 60 * 60 * 24));
        return diffInDays;
    }
    return !isNaN(parseInt(value)) ? parseInt(value) : null;
}
function ilike (str, pattern) { return __like(str, pattern, true) }
function __like(str, pattern, caseInsensitive = false) {
    if (caseInsensitive) {
        str = str.toLowerCase()
        pattern = pattern.toLowerCase()
    }
    pattern = String(pattern)
        .replaceAll(/[-/\\^$*+?.()|[\]{}]/g, '\\$&')
        .replaceAll('%', '.*')
        .replaceAll('_', '.')
    return new RegExp(pattern).test(str)
}
function toString (value) { return __STLToString(value) }
function __STLToString(arg) {
    if (arg && __isHogDate(arg)) {
        // Handle HogDate objects
        const month = arg.month.toString().padStart(2, '0');
        const day = arg.day.toString().padStart(2, '0');
        return `${arg.year}-${month}-${day}`;
    }
    if (arg && __isHogDateTime(arg)) {
        // Handle HogDateTime objects
        const dt = arg;
        const date = new Date(dt.dt * 1000);
        const timeZone = dt.zone || 'UTC';

        // Determine if milliseconds are present
        const milliseconds = Math.floor(dt.dt * 1000 % 1000);

        // Formatting options for date and time components
        const options = {
            timeZone,
            year: 'numeric',
            month: '2-digit',
            day: '2-digit',
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit',
            hour12: false,
        };

        // Create a formatter for the specified time zone
        const formatter = new Intl.DateTimeFormat('en-US', options);
        const parts = formatter.formatToParts(date);

        // Extract date and time components
        let year, month, day, hour, minute, second;
        for (const part of parts) {
            switch (part.type) {
                case 'year':
                    year = part.value;
                    break;
                case 'month':
                    month = part.value;
                    break;
                case 'day':
                    day = part.value;
                    break;
                case 'hour':
                    hour = part.value;
                    break;
                case 'minute':
                    minute = part.value;
                    break;
                case 'second':
                    second = part.value;
                    break;
                default:
                    // Ignore other parts
                    break;
            }
        }

        // Get time zone offset
        let offset = 'Z';
        if (timeZone === 'UTC') {
            offset = 'Z';
        } else {
            const tzOptions = { timeZone, timeZoneName: 'shortOffset' };
            const tzFormatter = new Intl.DateTimeFormat('en-US', tzOptions);
            const tzParts = tzFormatter.formatToParts(date);
            const timeZoneNamePart = tzParts.find(part => part.type === 'timeZoneName');

            if (timeZoneNamePart && timeZoneNamePart.value) {
                const offsetString = timeZoneNamePart.value;
                const match = offsetString.match(/GMT([+-]\d{2})(?::?(\d{2}))?/);
                if (match) {
                    const sign = match[1][0];
                    const hours = match[1].slice(1).padStart(2, '0');
                    const minutes = (match[2] || '00').padStart(2, '0');
                    offset = `${sign}${hours}:${minutes}`;
                } else if (offsetString === 'GMT') {
                    offset = '+00:00';
                } else {
                    // Fallback for time zones with names instead of offsets
                    offset = '';
                }
            }
        }

        // Build ISO 8601 string with time zone offset
        let isoString = `${year}-${month}-${day}T${hour}:${minute}:${second}`;
        if (milliseconds !== null) {
            isoString += `.${milliseconds.toString().padStart(3, '0')}`;
        }
        isoString += offset;

        return isoString;
    }
    // For other types, use default string representation
    return __printHogStringOutput(arg);
}
function __printHogStringOutput(obj) { if (typeof obj === 'string') { return obj } return __printHogValue(obj) }
function __printHogValue(obj, marked = new Set()) {
    if (typeof obj === 'object' && obj !== null && obj !== undefined) {
        if (marked.has(obj) && !__isHogDateTime(obj) && !__isHogDate(obj) && !__isHogError(obj)) {
            return 'null';
        }
        marked.add(obj);
        try {
            if (Array.isArray(obj)) {
                if (obj.__isHogTuple) {
                    return obj.length < 2 ? `tuple(${obj.map((o) => __printHogValue(o, marked)).join(', ')})` : `(${obj.map((o) => __printHogValue(o, marked)).join(', ')})`;
                }
                return `[${obj.map((o) => __printHogValue(o, marked)).join(', ')}]`;
            }
            if (__isHogDateTime(obj)) {
                const millis = String(obj.dt);
                return `DateTime(${millis}${millis.includes('.') ? '' : '.0'}, ${__escapeString(obj.zone)})`;
            }
            if (__isHogDate(obj)) return `Date(${obj.year}, ${obj.month}, ${obj.day})`;
            if (__isHogError(obj)) {
                return `${String(obj.type)}(${__escapeString(obj.message)}${obj.payload ? `, ${__printHogValue(obj.payload, marked)}` : ''})`;
            }
            if (obj instanceof Map) {
                return `{${Array.from(obj.entries()).map(([key, value]) => `${__printHogValue(key, marked)}: ${__printHogValue(value, marked)}`).join(', ')}}`;
            }
            return `{${Object.entries(obj).map(([key, value]) => `${__printHogValue(key, marked)}: ${__printHogValue(value, marked)}`).join(', ')}}`;
        } finally {
            marked.delete(obj);
        }
    } else if (typeof obj === 'boolean') return obj ? 'true' : 'false';
    else if (obj === null || obj === undefined) return 'null';
    else if (typeof obj === 'string') return __escapeString(obj);
            if (typeof obj === 'function') return `fn<${__escapeIdentifier(obj.name || 'lambda')}(${obj.length})>`;
    return obj.toString();
}
function __escapeIdentifier(identifier) {
    const backquoteEscapeCharsMap = { '\b': '\\b', '\f': '\\f', '\r': '\\r', '\n': '\\n', '\t': '\\t', '\0': '\\0', '\v': '\\v', '\\': '\\\\', '`': '\\`' }
    if (typeof identifier === 'number') return identifier.toString();
    if (/^[A-Za-z_$][A-Za-z0-9_$]*$/.test(identifier)) return identifier;
    return `\`${identifier.split('').map((c) => backquoteEscapeCharsMap[c] || c).join('')}\``;
}
function __escapeString(value) {
    const singlequoteEscapeCharsMap = { '\b': '\\b', '\f': '\\f', '\r': '\\r', '\n': '\\n', '\t': '\\t', '\0': '\\0', '\v': '\\v', '\\': '\\\\', "'": "\\'" }
    return `'${value.split('').map((c) => singlequoteEscapeCharsMap[c] || c).join('')}'`;
}
function __isHogError(obj) {return obj && obj.__hogError__ === true}
function toFloat(value) {
    if (__isHogDateTime(value)) {
        return value.dt;
    } else if (__isHogDate(value)) {
        const date = new Date(Date.UTC(value.year, value.month - 1, value.day));
        const epoch = new Date(Date.UTC(1970, 0, 1));
        const diffInDays = (date - epoch) / (1000 * 60 * 60 * 24);
        return diffInDays;
    }
    return !isNaN(parseFloat(value)) ? parseFloat(value) : null;
}
function __isHogDate(obj) { return obj && obj.__hogDate__ === true }
function __isHogDateTime(obj) { return obj && obj.__hogDateTime__ === true }

function test(val) {
    print(jsonStringify(val));
}
print("-- test the most common expressions --");
test((1 + 2));
test((1 - 2));
test((3 * 2));
test((3 / 2));
test((3 % 2));
test(!!(1 && 2));
test(!!(1 || 0));
test(!!(1 && 0));
test(!!(1 || !!(0 && 1) || 2));
test(!!(1 && 0 && 1));
test(!!(!!(1 || 2) && !!(1 || 2)));
test(true);
test((!true));
test(false);
test(null);
test(3.14);
test((1 == 2));
test((1 == 2));
test((1 != 2));
test((1 < 2));
test((1 <= 2));
test((1 > 2));
test((1 >= 2));
test(like("a", "b"));
test(like("baa", "%a%"));
test(like("baa", "%x%"));
test(ilike("baa", "%A%"));
test(ilike("baa", "%C%"));
test(ilike("a", "b"));
test(!like("a", "b"));
test(!ilike("a", "b"));
test(("car".includes("a")));
test(("foo".includes("a")));
test((!"car".includes("a")));
test(like("bax", "b_x"));
test(!like("baax", "b_x"));
test(like("baax", "b%x"));
test(concat("arg", "another"));
test(concat(1, null));
test(concat(true, false));
test(match("test", "e.*"));
test(match("test", "^e.*"));
test(match("test", "x.*"));
test(new RegExp("e.*").test("test"));
test(!(new RegExp("e.*").test("test")));
test(new RegExp("^e.*").test("test"));
test(!(new RegExp("^e.*").test("test")));
test(new RegExp("x.*").test("test"));
test(!(new RegExp("x.*").test("test")));
test(new RegExp("EST", "i").test("test"));
test(new RegExp("EST", "i").test("test"));
test(!(new RegExp("EST", "i").test("test")));
test(toString(1));
test(toString(1.5));
test(toString(true));
test(toString(null));
test(toString("string"));
test(toInt("1"));
test(toInt("bla"));
test(toFloat("1.2"));
test(toFloat("bla"));
test(toUUID("asd"));
test((1 == null));
test((1 != null));
test(("1" == 1));
test((1 == "1"));
test((1 == true));
test((0 == true));
test((2 == true));
test((1 != false));
test((1 == "2"));
test((1 == "2"));
test((1 != "2"));
test((1 < "2"));
test((1 <= "2"));
test((1 > "2"));
test((1 >= "2"));
test(("1" == 2));
test(("1" == 2));
test(("1" != 2));
test(("1" < 2));
test(("1" <= 2));
test(("1" > 2));
test(("1" >= 2));
