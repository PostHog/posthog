function concat (...args) {
    return args.map((arg) => (arg === null ? '' : __STLToString([arg]))).join('')
}

function print (...args) {
    console.log(...args.map(__printHogStringOutput))
}

function formatDateTime (input, format, zone) {
    return __formatDateTime(input, format, zone)
}

function __formatDateTime(input, format, zone) {
    if (!__isHogDateTime(input)) {
        throw new Error('Expected a DateTime')
    }
    if (!format) {
        throw new Error('formatDateTime requires at least 2 arguments')
    }
    let formatString = ''
    let acc = ''
    const tokenTranslations = {
        a: 'EEE',
        b: 'MMM',
        c: 'MM',
        C: 'yy',
        d: 'dd',
        D: 'MM/dd/yy',
        e: 'd',
        f: 'SSS',
        F: 'yyyy-MM-dd',
        g: 'yy',
        G: 'yyyy',
        h: 'hh',
        H: 'HH',
        i: 'mm',
        I: 'hh',
        j: 'ooo',
        k: 'HH',
        l: 'hh',
        m: 'MM',
        M: 'MMMM',
        n: '\n',
        p: 'a',
        Q: 'q',
        r: 'hh:mm a',
        R: 'HH:mm',
        s: 'ss',
        S: 'ss',
        t: '\t',
        T: 'HH:mm:ss',
        u: 'E',
        V: 'WW',
        w: 'E',
        W: 'EEEE',
        y: 'yy',
        Y: 'yyyy',
        z: 'ZZZ',
        '%': '%',
    }
    for (let i = 0; i < format.length; i++) {
        if (format[i] === '%') {
            if (acc.length > 0) {
                formatString += `'\${acc}'`
                acc = ''
            }
            i += 1
            if (i < format.length && tokenTranslations[format[i]]) {
                formatString += tokenTranslations[format[i]]
            }
        } else {
            acc += format[i]
        }
    }
    if (acc.length > 0) {
        formatString += `'\${acc}'`
    }
    return DateTime.fromSeconds(input.dt, { zone: zone || input.zone }).toFormat(formatString)
}

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

function __printHogStringOutput(obj) {
    if (typeof obj === 'string') {
        return obj
    }
    return __printHogValue(obj)
}

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
    else if (typeof obj === 'function') return `fn<${__escapeIdentifier(obj.name ?? 'lambda')}(${obj.length})>`;
    return obj.toString();
}

function __escapeIdentifier(identifier) {
    const backquoteEscapeCharsMap = {
        '\b': '\\b',
        '\f': '\\f',
        '\r': '\\r',
        '\n': '\\n',
        '\t': '\\t',
        '\0': '\\0',
        '\v': '\\v',
        '\\': '\\\\',
        '`': '\\`',
    }
    if (typeof identifier === 'number') return identifier.toString();
    if (/^[A-Za-z_$][A-Za-z0-9_$]*$/.test(identifier)) return identifier;
    return `\`${identifier.split('').map((c) => backquoteEscapeCharsMap[c] || c).join('')}\``;
}

function __escapeString(value) {
    const singlequoteEscapeCharsMap = {
        '\b': '\\b',
        '\f': '\\f',
        '\r': '\\r',
        '\n': '\\n',
        '\t': '\\t',
        '\0': '\\0',
        '\v': '\\v',
        '\\': '\\\\',
        "'": "\\'",
    }
    return `'${value.split('').map((c) => singlequoteEscapeCharsMap[c] || c).join('')}'`;
}

function __isHogCallable(obj) {
    return obj && typeof obj === 'function' && obj.__isHogCallable__
}

function __isHogClosure(obj) {
    return obj && obj.__isHogClosure__ === true
}

function __isHogError(obj) {
    return obj && obj.__hogError__ === true
}

function __isHogDateTime(obj) {
    return obj && obj.__hogDateTime__ === true
}

function fromUnixTimestamp (input) {
    return __fromUnixTimestamp(input)
}

function __fromUnixTimestamp(input) {
    return __toHogDateTime(input)
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

function __isHogDate(obj) {
    return obj && obj.__hogDate__ === true
}

let dt = fromUnixTimestamp(1234377543.123456);
print(formatDateTime(dt, "%Y-%m-%d %H:%i:%S"));
print(formatDateTime(dt, "%Y-%m-%d %H:%i:%S", "Europe/Brussels"));
print(formatDateTime(dt, "%Y-%m-%d %H:%i:%S", "America/New_York"));
print(formatDateTime(dt, "%Y%m%dT%H%i%sZ"));
print("-----");
print(concat("%a: ", formatDateTime(dt, "%a")));
print(concat("%b: ", formatDateTime(dt, "%b")));
print(concat("%c: ", formatDateTime(dt, "%c")));
print(concat("%C: ", formatDateTime(dt, "%C")));
print(concat("%d: ", formatDateTime(dt, "%d")));
print(concat("%D: ", formatDateTime(dt, "%D")));
print(concat("%e: ", formatDateTime(dt, "%e")));
print(concat("%F: ", formatDateTime(dt, "%F")));
print(concat("%g: ", formatDateTime(dt, "%g")));
print(concat("%G: ", formatDateTime(dt, "%G")));
print(concat("%h: ", formatDateTime(dt, "%h")));
print(concat("%H: ", formatDateTime(dt, "%H")));
print(concat("%i: ", formatDateTime(dt, "%i")));
print(concat("%I: ", formatDateTime(dt, "%I")));
print(concat("%j: ", formatDateTime(dt, "%j")));
print(concat("%k: ", formatDateTime(dt, "%k")));
print(concat("%l: ", formatDateTime(dt, "%l")));
print(concat("%m: ", formatDateTime(dt, "%m")));
print(concat("%M: ", formatDateTime(dt, "%M")));
print(concat("%n: ", formatDateTime(dt, "%n")));
print(concat("%p: ", formatDateTime(dt, "%p")));
print(concat("%r: ", formatDateTime(dt, "%r")));
print(concat("%R: ", formatDateTime(dt, "%R")));
print(concat("%s: ", formatDateTime(dt, "%s")));
print(concat("%S: ", formatDateTime(dt, "%S")));
print(concat("%t: ", formatDateTime(dt, "%t")));
print(concat("%T: ", formatDateTime(dt, "%T")));
print(concat("%u: ", formatDateTime(dt, "%u")));
print(concat("%V: ", formatDateTime(dt, "%V")));
print(concat("%w: ", formatDateTime(dt, "%w")));
print(concat("%W: ", formatDateTime(dt, "%W")));
print(concat("%y: ", formatDateTime(dt, "%y")));
print(concat("%Y: ", formatDateTime(dt, "%Y")));
print(concat("%z: ", formatDateTime(dt, "%z")));
print(concat("%%: ", formatDateTime(dt, "%%")));
print("-----");
print(formatDateTime(dt, "one banana"));
print(formatDateTime(dt, "%Y no way %m is this %d a %H real %i time %S"));
