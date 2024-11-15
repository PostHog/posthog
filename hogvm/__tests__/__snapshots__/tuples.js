function tuple (...args) { const tuple = args.slice(); tuple.__isHogTuple = true; return tuple; }
function print (...args) { console.log(...args.map(__printHogStringOutput)) }
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
function __isHogDateTime(obj) { return obj && obj.__hogDateTime__ === true }
function __isHogDate(obj) { return obj && obj.__hogDate__ === true }
function __getProperty(objectOrArray, key, nullish) {
    if ((nullish && !objectOrArray) || key === 0) { return null }
    if (Array.isArray(objectOrArray)) {
        return key > 0 ? objectOrArray[key - 1] : objectOrArray[objectOrArray.length + key]
    } else {
        return objectOrArray[key]
    }
}
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

print(tuple());
print(tuple(1));
print(tuple(1, 2));
print(tuple(1, 2));
print(tuple(1, 2, 3));
print(tuple(1, "2", 3));
print(tuple(1, tuple(2, 3), 4));
print(tuple(1, tuple(2, tuple(3, 4)), 5));
let a = tuple(1, 2, 3);
print(__getProperty(a, 2, false));
print(__getProperty(a, 2, true));
print(__getProperty(a, 8, true));
print(__getProperty(__getProperty(__getProperty(tuple(1, tuple(2, tuple(3, 4)), 5), 2, false), 2, false), 2, false));
print(__getProperty(__getProperty(__getProperty(tuple(1, tuple(2, tuple(3, 4)), 5), 2, true), 2, true), 2, true));
print(__getProperty(__getProperty(__getProperty(tuple(1, tuple(2, tuple(3, 4)), 5), 2, true), 2, true), 2, true));
print(__getProperty(__getProperty(__getProperty(tuple(1, tuple(2, tuple(3, 4)), 5), 4, true), 7, true), 2, true));
print(__getProperty(__getProperty(__getProperty(tuple(1, tuple(2, tuple(3, 4)), 5), 4, true), 7, true), 2, true));
print(__getProperty(__getProperty(__getProperty(tuple(1, tuple(2, tuple(3, 4)), 5), 2, false), 2, false), 2, false));
print((__getProperty(__getProperty(__getProperty(tuple(1, tuple(2, tuple(3, 4)), 5), 2, false), 2, false), 2, false) + 1));
