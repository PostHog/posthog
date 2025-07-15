function print (...args) { console.log(...args.map(__printHogStringOutput)) }
function fromUnixTimestamp (input) { return __fromUnixTimestamp(input) }
function formatDateTime (input, format, zone) { return __formatDateTime(input, format, zone) }
function concat (...args) { return args.map((arg) => (arg === null ? '' : __STLToString(arg))).join('') }
function __fromUnixTimestamp(input) { return __toHogDateTime(input) }
function __toHogDateTime(timestamp, zone) {
    if (__isHogDate(timestamp)) {
        const date = new Date(Date.UTC(timestamp.year, timestamp.month - 1, timestamp.day));
        const dt = date.getTime() / 1000;
        return { __hogDateTime__: true, dt: dt, zone: zone || 'UTC' };
    }
    return { __hogDateTime__: true, dt: timestamp, zone: zone || 'UTC' }; }
function __formatDateTime(input, format, zone) {
    if (!__isHogDateTime(input)) { throw new Error('Expected a DateTime'); }
    if (!format) { throw new Error('formatDateTime requires at least 2 arguments'); }
    const timestamp = input.dt * 1000;
    let date = new Date(timestamp);
    if (!zone) { zone = 'UTC'; }
    const padZero = (num, len = 2) => String(num).padStart(len, '0');
    const padSpace = (num, len = 2) => String(num).padStart(len, ' ');
    const getDateComponent = (type, options = {}) => {
        const formatter = new Intl.DateTimeFormat('en-US', { ...options, timeZone: zone });
        const parts = formatter.formatToParts(date);
        const part = parts.find(p => p.type === type);
        return part ? part.value : '';
    };
    const getNumericComponent = (type, options = {}) => {
        const value = getDateComponent(type, options);
        return parseInt(value, 10);
    };
    const getWeekNumber = (d) => {
        const dateInZone = new Date(d.toLocaleString('en-US', { timeZone: zone }));
        const target = new Date(Date.UTC(dateInZone.getFullYear(), dateInZone.getMonth(), dateInZone.getDate()));
        const dayNr = (target.getUTCDay() + 6) % 7;
        target.setUTCDate(target.getUTCDate() - dayNr + 3);
        const firstThursday = new Date(Date.UTC(target.getUTCFullYear(), 0, 4));
        const weekNumber = 1 + Math.round(((target - firstThursday) / 86400000 - 3 + ((firstThursday.getUTCDay() + 6) % 7)) / 7);
        return weekNumber;
    };
    const getDayOfYear = (d) => {
        const startOfYear = new Date(Date.UTC(d.getUTCFullYear(), 0, 1));
        const dateInZone = new Date(d.toLocaleString('en-US', { timeZone: zone }));
        const diff = dateInZone - startOfYear;
        return Math.floor(diff / 86400000) + 1;
    };
    // Token mapping with corrections
    const tokens = {
        '%a': () => getDateComponent('weekday', { weekday: 'short' }),
        '%b': () => getDateComponent('month', { month: 'short' }),
        '%c': () => padZero(getNumericComponent('month', { month: '2-digit' })),
        '%C': () => getDateComponent('year', { year: '2-digit' }),
        '%d': () => padZero(getNumericComponent('day', { day: '2-digit' })),
        '%D': () => {
            const month = padZero(getNumericComponent('month', { month: '2-digit' }));
            const day = padZero(getNumericComponent('day', { day: '2-digit' }));
            const year = getDateComponent('year', { year: '2-digit' });
            return `${month}/${day}/${year}`;
        },
        '%e': () => padSpace(getNumericComponent('day', { day: 'numeric' })),
        '%F': () => {
            const year = getNumericComponent('year', { year: 'numeric' });
            const month = padZero(getNumericComponent('month', { month: '2-digit' }));
            const day = padZero(getNumericComponent('day', { day: '2-digit' }));
            return `${year}-${month}-${day}`;
        },
        '%g': () => getDateComponent('year', { year: '2-digit' }),
        '%G': () => getNumericComponent('year', { year: 'numeric' }),
        '%h': () => padZero(getNumericComponent('hour', { hour: '2-digit', hour12: true })),
        '%H': () => padZero(getNumericComponent('hour', { hour: '2-digit', hour12: false })),
        '%i': () => padZero(getNumericComponent('minute', { minute: '2-digit' })),
        '%I': () => padZero(getNumericComponent('hour', { hour: '2-digit', hour12: true })),
        '%j': () => padZero(getDayOfYear(date), 3),
        '%k': () => padSpace(getNumericComponent('hour', { hour: 'numeric', hour12: false })),
        '%l': () => padZero(getNumericComponent('hour', { hour: '2-digit', hour12: true })),
        '%m': () => padZero(getNumericComponent('month', { month: '2-digit' })),
        '%M': () => getDateComponent('month', { month: 'long' }),
        '%n': () => '\n',
        '%p': () => getDateComponent('dayPeriod', { hour: 'numeric', hour12: true }),
        '%r': () => {
            const hour = padZero(getNumericComponent('hour', { hour: '2-digit', hour12: true }));
            const minute = padZero(getNumericComponent('minute', { minute: '2-digit' }));
            const second = padZero(getNumericComponent('second', { second: '2-digit' }));
            const period = getDateComponent('dayPeriod', { hour: 'numeric', hour12: true });
            return `${hour}:${minute} ${period}`;
        },
        '%R': () => {
            const hour = padZero(getNumericComponent('hour', { hour: '2-digit', hour12: false }));
            const minute = padZero(getNumericComponent('minute', { minute: '2-digit' }));
            return `${hour}:${minute}`;
        },
        '%s': () => padZero(getNumericComponent('second', { second: '2-digit' })),
        '%S': () => padZero(getNumericComponent('second', { second: '2-digit' })),
        '%t': () => '\t',
        '%T': () => {
            const hour = padZero(getNumericComponent('hour', { hour: '2-digit', hour12: false }));
            const minute = padZero(getNumericComponent('minute', { minute: '2-digit' }));
            const second = padZero(getNumericComponent('second', { second: '2-digit' }));
            return `${hour}:${minute}:${second}`;
        },
        '%u': () => {
            let day = getDateComponent('weekday', { weekday: 'short' });
            const dayMap = { 'Mon': '1', 'Tue': '2', 'Wed': '3', 'Thu': '4', 'Fri': '5', 'Sat': '6', 'Sun': '7' };
            return dayMap[day];
        },
        '%V': () => padZero(getWeekNumber(date)),
        '%w': () => {
            let day = getDateComponent('weekday', { weekday: 'short' });
            const dayMap = { 'Sun': '0', 'Mon': '1', 'Tue': '2', 'Wed': '3', 'Thu': '4', 'Fri': '5', 'Sat': '6' };
            return dayMap[day];
        },
        '%W': () => getDateComponent('weekday', { weekday: 'long' }),
        '%y': () => getDateComponent('year', { year: '2-digit' }),
        '%Y': () => getNumericComponent('year', { year: 'numeric' }),
        '%z': () => {
            if (zone === 'UTC') {
                return '+0000';
            } else {
                const formatter = new Intl.DateTimeFormat('en-US', {
                    timeZone: zone,
                    timeZoneName: 'shortOffset',
                });
                const parts = formatter.formatToParts(date);
                const offsetPart = parts.find(part => part.type === 'timeZoneName');
                if (offsetPart && offsetPart.value) {
                    const offsetValue = offsetPart.value;
                    const match = offsetValue.match(/GMT([+-]\d{1,2})(?::(\d{2}))?/);
                    if (match) {
                        const sign = match[1][0];
                        const hours = padZero(Math.abs(parseInt(match[1], 10)));
                        const minutes = padZero(match[2] ? parseInt(match[2], 10) : 0);
                        return `${sign}${hours}${minutes}`;
                    }
                }
                return '';
            }
        },
        '%%': () => '%',
    };

    // Replace tokens in the format string
    let result = '';
    let i = 0;
    while (i < format.length) {
        if (format[i] === '%') {
            const token = format.substring(i, i + 2);
            if (tokens[token]) {
                result += tokens[token]();
                i += 2;
            } else {
                // If token not found, include '%' and move to next character
                result += format[i];
                i += 1;
            }
        } else {
            result += format[i];
            i += 1;
        }
    }

    return result;
}
function __STLToString(arg) {
    if (arg && __isHogDate(arg)) { return `${arg.year}-${arg.month.toString().padStart(2, '0')}-${arg.day.toString().padStart(2, '0')}`; }
    else if (arg && __isHogDateTime(arg)) { return __DateTimeToString(arg); }
    return __printHogStringOutput(arg); }
function __printHogStringOutput(obj) { if (typeof obj === 'string') { return obj } return __printHogValue(obj) }
function __printHogValue(obj, marked = new Set()) {
    if (typeof obj === 'object' && obj !== null && obj !== undefined) {
        if (marked.has(obj) && !__isHogDateTime(obj) && !__isHogDate(obj) && !__isHogError(obj)) { return 'null'; }
        marked.add(obj);
        try {
            if (Array.isArray(obj)) {
                if (obj.__isHogTuple) { return obj.length < 2 ? `tuple(${obj.map((o) => __printHogValue(o, marked)).join(', ')})` : `(${obj.map((o) => __printHogValue(o, marked)).join(', ')})`; }
                return `[${obj.map((o) => __printHogValue(o, marked)).join(', ')}]`;
            }
            if (__isHogDateTime(obj)) { const millis = String(obj.dt); return `DateTime(${millis}${millis.includes('.') ? '' : '.0'}, ${__escapeString(obj.zone)})`; }
            if (__isHogDate(obj)) return `Date(${obj.year}, ${obj.month}, ${obj.day})`;
            if (__isHogError(obj)) { return `${String(obj.type)}(${__escapeString(obj.message)}${obj.payload ? `, ${__printHogValue(obj.payload, marked)}` : ''})`; }
            if (obj instanceof Map) { return `{${Array.from(obj.entries()).map(([key, value]) => `${__printHogValue(key, marked)}: ${__printHogValue(value, marked)}`).join(', ')}}`; }
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
function __isHogError(obj) {return obj && obj.__hogError__ === true}
function __escapeString(value) {
    const singlequoteEscapeCharsMap = { '\b': '\\b', '\f': '\\f', '\r': '\\r', '\n': '\\n', '\t': '\\t', '\0': '\\0', '\v': '\\v', '\\': '\\\\', "'": "\\'" }
    return `'${value.split('').map((c) => singlequoteEscapeCharsMap[c] || c).join('')}'`;
}
function __escapeIdentifier(identifier) {
    const backquoteEscapeCharsMap = { '\b': '\\b', '\f': '\\f', '\r': '\\r', '\n': '\\n', '\t': '\\t', '\0': '\\0', '\v': '\\v', '\\': '\\\\', '`': '\\`' }
    if (typeof identifier === 'number') return identifier.toString();
    if (/^[A-Za-z_$][A-Za-z0-9_$]*$/.test(identifier)) return identifier;
    return `\`${identifier.split('').map((c) => backquoteEscapeCharsMap[c] || c).join('')}\``;
}
function __isHogDateTime(obj) { return obj && obj.__hogDateTime__ === true }
function __isHogDate(obj) { return obj && obj.__hogDate__ === true }
function __DateTimeToString(dt) {
    if (__isHogDateTime(dt)) {
        const date = new Date(dt.dt * 1000);
        const timeZone = dt.zone || 'UTC';
        const milliseconds = Math.floor(dt.dt * 1000 % 1000);
        const options = { timeZone, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false };
        const formatter = new Intl.DateTimeFormat('en-US', options);
        const parts = formatter.formatToParts(date);
        let year, month, day, hour, minute, second;
        for (const part of parts) {
            switch (part.type) {
                case 'year': year = part.value; break;
                case 'month': month = part.value; break;
                case 'day': day = part.value; break;
                case 'hour': hour = part.value; break;
                case 'minute': minute = part.value; break;
                case 'second': second = part.value; break;
                default: break;
            }
        }
        const getOffset = (date, timeZone) => {
            const tzDate = new Date(date.toLocaleString('en-US', { timeZone }));
            const utcDate = new Date(date.toLocaleString('en-US', { timeZone: 'UTC' }));
            const offset = (tzDate - utcDate) / 60000; // in minutes
            const sign = offset >= 0 ? '+' : '-';
            const absOffset = Math.abs(offset);
            const hours = Math.floor(absOffset / 60);
            const minutes = absOffset % 60;
            return `${sign}${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}`;
        };
        let offset = 'Z';
        if (timeZone !== 'UTC') {
            offset = getOffset(date, timeZone);
        }
        let isoString = `${year}-${month}-${day}T${hour}:${minute}:${second}`;
        isoString += `.${milliseconds.toString().padStart(3, '0')}`;
        isoString += offset;
        return isoString;
    }
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
