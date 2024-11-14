function __x_Error (message, payload) { return __newHogError('Error', message, payload) }
function print (...args) { console.log(...args.map(__printHogStringOutput)) }
function __printHogStringOutput(obj) { if (typeof obj === 'string') { return obj } return __printHogValue(obj) }
function __lambda (fn) { return fn }
function toDate (input) { return __toDate(input) }
function __toDate(input) { const dt = typeof input === 'number' ? DateTime.fromSeconds(input) : DateTime.fromISO(input); return { __hogDate__: true, year: dt.year, month: dt.month, day: dt.day, } }
function __x_typeof (value) {
    if (value === null || value === undefined) {
        return 'null'
    } else if (__isHogDateTime(value)) {
        return 'datetime'
    } else if (__isHogDate(value)) {
        return 'date'
    } else if (__isHogError(value)) {
        return 'error'
    } else if (__isHogCallable(value) || __isHogClosure(value)) {
        return 'function'
    } else if (Array.isArray(value)) {
        if (value.__isHogTuple) {
            return 'tuple'
        }
        return 'array'
    } else if (typeof value === 'object') {
        return 'object'
    } else if (typeof value === 'number') {
        return Number.isInteger(value) ? 'integer' : 'float'
    } else if (typeof value === 'string') {
        return 'string'
    } else if (typeof value === 'boolean') {
        return 'boolean'
    }
    return 'unknown'
}
function __newHogError(type, message, payload) {
    let error = new Error(message || 'An error occurred');
    error.__hogError__ = true
    error.type = type
    error.payload = payload
    return error
}
function tuple (...args) { const tuple = args.slice(); tuple.__isHogTuple = true; return tuple; }
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
function __isHogDate(obj) { return obj && obj.__hogDate__ === true }
function __isHogDateTime(obj) { return obj && obj.__hogDateTime__ === true }
function toDateTime (input, zone) { return __toDateTime(input, zone) }
function __toDateTime(input, zone) {
    const dt = typeof input === 'number' ? input : DateTime.fromISO(input, { zone: zone || 'UTC' }).toSeconds()
    return {
        __hogDateTime__: true,
        dt: dt,
        zone: zone || 'UTC',
    }
}

function test(obj) {
    print(__x_typeof(obj));
}
test("hello world");
test(123);
test(1.23);
test(true);
test(false);
test(null);
test({});
test([]);
test(tuple(1, 2, 3));
test(__lambda(() => (1 + 2)));
test(toDateTime("2021-01-01T00:00:00Z"));
test(toDate("2021-01-01"));
test(__x_Error("BigError", "message"));
