function toDate (input) { return __toDate(input) }
function __toDate(input) { const dt = typeof input === 'number' ? DateTime.fromSeconds(input) : DateTime.fromISO(input); return { __hogDate__: true, year: dt.year, month: dt.month, day: dt.day, } }
function toUnixTimestamp (input, zone) { return __toUnixTimestamp(input, zone) }
function toDateTime (input, zone) { return __toDateTime(input, zone) }
function fromUnixTimestampMilli (input) { return __fromUnixTimestampMilli(input) }
function toString (value) { return __STLToString([value]) }
function print (...args) { console.log(...args.map(__printHogStringOutput)) }
function __toDateTime(input, zone) {
    const dt = typeof input === 'number' ? input : DateTime.fromISO(input, { zone: zone || 'UTC' }).toSeconds()
    return {
        __hogDateTime__: true,
        dt: dt,
        zone: zone || 'UTC',
    }
}
function toTimeZone (input, zone) { return __toTimeZone(input, zone) }
function __toTimeZone(input, zone) { if (!__isHogDateTime(input)) { throw new Error('Expected a DateTime') }; return { ...input, zone }}
function toFloat (value) {
    if (__isHogDateTime(value)) {
        return value.dt
    } else if (__isHogDate(value)) {
        const day = DateTime.fromObject({ year: value.year, month: value.month, day: value.day })
        const epoch = DateTime.fromObject({ year: 1970, month: 1, day: 1 })
        return Math.floor(day.diff(epoch, 'days').days)
    }
    return !isNaN(parseFloat(value)) ? parseFloat(value) : null}
function __fromUnixTimestampMilli(input) { return __toHogDateTime(input / 1000) }
function __STLToString(args) {
    if (__isHogDate(args[0])) {
        const month = args[0].month
        const day = args[0].day
        return `\${args[0].year}-\${month < 10 ? '0' : ''}\${month}-\${day < 10 ? '0' : ''}\${day}`
    }
    if (__isHogDateTime(args[0])) {
        return DateTime.fromSeconds(args[0].dt, { zone: args[0].zone }).toISO()
    }
    return __printHogStringOutput(args[0])
}
function __printHogStringOutput(obj) { if (typeof obj === 'string') { return obj } return __printHogValue(obj) }
function __printHogValue(obj, marked = new Set()) {
    if (typeof obj === 'object' && obj !== null && obj !== undefined) {
        if (marked.has(obj) && !__isHogDateTime(obj) && !__isHogDate(obj) && !__isHogError(obj) && !__isHogClosure(obj) && !__isHogCallable(obj)) {
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
            if (__isHogClosure(obj)) return __printHogValue(obj.callable, marked);
            if (__isHogCallable(obj)) return `fn<${__escapeIdentifier(obj.name ?? 'lambda')}(${__printHogValue(obj.argCount)})>`;
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
function __isHogCallable(obj) { return obj && typeof obj === 'function' && obj.__isHogCallable__ }
function __isHogClosure(obj) { return obj && obj.__isHogClosure__ === true }
function __isHogError(obj) {return obj && obj.__hogError__ === true}
function fromUnixTimestamp (input) { return __fromUnixTimestamp(input) }
function __fromUnixTimestamp(input) { return __toHogDateTime(input) }
function toInt (value) {
    if (__isHogDateTime(value)) {
        return Math.floor(value.dt)
    } else if (__isHogDate(value)) {
        const day = DateTime.fromObject({ year: value.year, month: value.month, day: value.day })
        const epoch = DateTime.fromObject({ year: 1970, month: 1, day: 1 })
        return Math.floor(day.diff(epoch, 'days').days)
    }
    return !isNaN(parseInt(value)) ? parseInt(value) : null
}
function toUnixTimestampMilli (input, zone) { return __toUnixTimestampMilli(input, zone) }
function __toUnixTimestampMilli(input, zone) { return __toUnixTimestamp(input, zone) * 1000 }
function __toUnixTimestamp(input, zone) {
    if (__isHogDateTime(input)) {
        return input.dt
    }
    if (__isHogDate(input)) {
        return __toHogDateTime(input).dt
    }
    return DateTime.fromISO(input, { zone: zone || 'UTC' }).toSeconds()
}
function __toHogDateTime(timestamp, zone) {
    if (__isHogDate(timestamp)) {
        const dateTime = DateTime.fromObject(
            {
                year: timestamp.year,
                month: timestamp.month,
                day: timestamp.day,
            },
            { zone: zone || 'UTC' }
        )
        return {
            __hogDateTime__: true,
            dt: dateTime.toSeconds(),
            zone: dateTime.zoneName || 'UTC',
        }
    }
    return {
        __hogDateTime__: true,
        dt: timestamp,
        zone: zone || 'UTC',
    }
}
function __isHogDate(obj) { return obj && obj.__hogDate__ === true }
function __isHogDateTime(obj) { return obj && obj.__hogDateTime__ === true }

let dt = fromUnixTimestamp(1234334543);
print(dt);
print(toString(dt));
print(toInt(toUnixTimestamp(dt)));
print("-");
let dt2 = toDate("2024-05-03");
print(dt2);
print(toString(dt2));
print(toInt(toUnixTimestamp(dt2)));
print("-");
let dt3 = toDateTime("2024-05-03T12:34:56Z");
print(dt3);
print(toString(dt3));
print(toInt(toUnixTimestamp(dt3)));
print("------");
print(toTimeZone(dt3, "Europe/Brussels"));
print(toString(toTimeZone(dt3, "Europe/Brussels")));
print("-");
print(toTimeZone(dt3, "Europe/Tallinn"));
print(toString(toTimeZone(dt3, "Europe/Tallinn")));
print("-");
print(toTimeZone(dt3, "America/New_York"));
print(toString(toTimeZone(dt3, "America/New_York")));
print("------");
let timestamp = fromUnixTimestamp(1234334543.123);
print("timestamp:                                ", timestamp);
print("toString(timestamp):                      ", toString(timestamp));
print("toInt(timestamp):                         ", toInt(timestamp));
print("toDateTime(toInt(timestamp)):             ", toDateTime(toInt(timestamp)));
print("toInt(toDateTime(toInt(timestamp))):      ", toInt(toDateTime(toInt(timestamp))));
print("toString(toDateTime(toInt(timestamp))):   ", toString(toDateTime(toInt(timestamp))));
print("toFloat(timestamp):                       ", toFloat(timestamp));
print("toDateTime(toFloat(timestamp)):           ", toDateTime(toFloat(timestamp)));
print("toFloat(toDateTime(toFloat(timestamp))):  ", toFloat(toDateTime(toFloat(timestamp))));
print("toString(toDateTime(toFloat(timestamp))): ", toString(toDateTime(toFloat(timestamp))));
print("------");
let millisTs = fromUnixTimestampMilli(1234334543123);
print("millisTs:                                 ", toString(millisTs));
print("toString(millisTs):                       ", toString(millisTs));
print("toInt(millisTs):                          ", toInt(millisTs));
print("toFloat(millisTs):                        ", toFloat(millisTs));
print("toUnixTimestampMilli(millisTs):           ", toUnixTimestampMilli(millisTs));
print("------");
let date = toDate("2024-05-03");
print(date);
print(toString(date));
print(toInt(date));
