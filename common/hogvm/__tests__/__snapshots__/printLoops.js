function print (...args) { console.log(...args.map(__printHogStringOutput)) }
function jsonStringify (value, spacing) {
    function convert(x, marked) {
        if (!marked) { marked = new Set() }
        if (typeof x === 'object' && x !== null) {
            if (marked.has(x)) { return null }
            marked.add(x)
            try {
                if (x instanceof Map) {
                    const obj = {}
                    x.forEach((value, key) => { obj[convert(key, marked)] = convert(value, marked) })
                    return obj
                }
                if (Array.isArray(x)) { return x.map((v) => convert(v, marked)) }
                if (__isHogDateTime(x) || __isHogDate(x) || __isHogError(x)) { return x }
                if (typeof x === 'function') { return `fn<${x.name || 'lambda'}(${x.length})>` }
                const obj = {}; for (const key in x) { obj[key] = convert(x[key], marked) }
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
    return JSON.stringify(convert(value), (key, val) => typeof val === 'function' ? `fn<${val.name || 'lambda'}(${val.length})>` : val)
}
function jsonParse (str) {
    function convert(x) {
        if (Array.isArray(x)) { return x.map(convert) }
        else if (typeof x === 'object' && x !== null) {
            if (x.__hogDateTime__) { return __toHogDateTime(x.dt, x.zone)
            } else if (x.__hogDate__) { return __toHogDate(x.year, x.month, x.day)
            } else if (x.__hogError__) { return __newHogError(x.type, x.message, x.payload) }
            const obj = {}; for (const key in x) { obj[key] = convert(x[key]) }; return obj }
        return x }
    return convert(JSON.parse(str)) }
function concat (...args) { return args.map((arg) => (arg === null ? '' : __STLToString(arg))).join('') }
function __toHogDateTime(timestamp, zone) {
    if (__isHogDate(timestamp)) {
        const date = new Date(Date.UTC(timestamp.year, timestamp.month - 1, timestamp.day));
        const dt = date.getTime() / 1000;
        return { __hogDateTime__: true, dt: dt, zone: zone || 'UTC' };
    }
    return { __hogDateTime__: true, dt: timestamp, zone: zone || 'UTC' }; }
function __toHogDate(year, month, day) { return { __hogDate__: true, year: year, month: month, day: day, } }
function __setProperty(objectOrArray, key, value) {
    if (Array.isArray(objectOrArray)) { if (key > 0) { objectOrArray[key - 1] = value } else { objectOrArray[objectOrArray.length + key] = value } }
    else { objectOrArray[key] = value }
    return objectOrArray
}
function __newHogError(type, message, payload) {
    let error = new Error(message || 'An error occurred');
    error.__hogError__ = true
    error.type = type
    error.payload = payload
    return error
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

let obj = {"key": "value", "key2": "value2"};
let str = "na";
for (let i = 0; (i < 100); i = (i + 1)) {
    str = concat(str, "na")
    __setProperty(obj, concat("key_", i), {"wasted": concat("memory: ", str, " batman!"), "something": obj});
}
print(obj);
let json = jsonStringify(obj);
print(jsonParse(json));
