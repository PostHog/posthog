function jsonParse (str) {
    function convert(x) {
        if (Array.isArray(x)) {
            return x.map(convert)
        } else if (typeof x === 'object' && x !== null) {
            if (x.__hogDateTime__) {
                return __toHogDateTime(x.dt, x.zone)
            } else if (x.__hogDate__) {
                return __toHogDate(x.year, x.month, x.day)
            } else if (x.__hogError__) {
                return __newHogError(x.type, x.message, x.payload)
            }
            const map = new Map()
            for (const key in x) {
                map.set(key, convert(x[key]))
            }
            return map
        }
        return x
    }
    return convert(JSON.parse(str))
}
function print (...args) { console.log(...args.map(__printHogStringOutput)) }
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
function __newHogError(type, message, payload) {
    let error = new Error(message || 'An error occurred');
    error.__hogError__ = true
    error.type = type
    error.payload = payload
    return error
}
function __toHogDateTime(timestamp, zone) {
    if (__isHogDate(timestamp)) {
        const date = new Date(Date.UTC(timestamp.year, timestamp.month - 1, timestamp.day));
        const dt = date.getTime() / 1000;
        return {
            __hogDateTime__: true,
            dt: dt,
            zone: zone || 'UTC',
        };
    }
    return {
        __hogDateTime__: true,
        dt: timestamp,
        zone: zone || 'UTC',
    };
}
function concat (...args) { return args.map((arg) => (arg === null ? '' : __STLToString(arg))).join('') }
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
function __isHogError(obj) {return obj && obj.__hogError__ === true}
function __isHogDateTime(obj) { return obj && obj.__hogDateTime__ === true }
function __toHogDate(year, month, day) { return { __hogDate__: true, year: year, month: month, day: day, } }
function __isHogDate(obj) { return obj && obj.__hogDate__ === true }
function __setProperty(objectOrArray, key, value) {
    if (Array.isArray(objectOrArray)) {
        if (key > 0) {
            objectOrArray[key - 1] = value
        } else {
            objectOrArray[objectOrArray.length + key] = value
        }
    } else {
        objectOrArray[key] = value
    }
    return objectOrArray
}
function __escapeString(value) {
    const singlequoteEscapeCharsMap = { '\b': '\\b', '\f': '\\f', '\r': '\\r', '\n': '\\n', '\t': '\\t', '\0': '\\0', '\v': '\\v', '\\': '\\\\', "'": "\\'" }
    return `'${value.split('').map((c) => singlequoteEscapeCharsMap[c] || c).join('')}'`;
}

let root = {"key": "value", "key2": "value2"};
let leaf = {"key": "value", "key2": "value2"};
for (let i = 0; (i < 30); i = (i + 1)) {
    __setProperty(root, concat("key_", i), {"something": leaf});
}
print(root);
print(jsonParse(jsonStringify(root)));
