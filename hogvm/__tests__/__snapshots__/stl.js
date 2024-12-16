function upper (value) { return value.toUpperCase() }
function tuple (...args) { const tuple = args.slice(); tuple.__isHogTuple = true; return tuple; }
function reverse (value) { return value.split('').reverse().join('') }
function replaceOne (str, searchValue, replaceValue) { return str.replace(searchValue, replaceValue) }
function replaceAll (str, searchValue, replaceValue) { return str.replaceAll(searchValue, replaceValue) }
function print (...args) { console.log(...args.map(__printHogStringOutput)) }
function notEmpty (value) { return !empty(value) }
function lower (value) { return value.toLowerCase() }
function length (value) { return value.length }
function generateUUIDv4 () { return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function (c) { const r = (Math.random() * 16) | 0; const v = c === 'x' ? r : (r & 0x3) | 0x8; return v.toString(16) })}
function encodeURLComponent (str) { return encodeURIComponent(str) }
function empty (value) {
    if (typeof value === 'object') {
        if (Array.isArray(value)) { return value.length === 0 } else if (value === null) { return true } else if (value instanceof Map) { return value.size === 0 }
        return Object.keys(value).length === 0
    } else if (typeof value === 'number' || typeof value === 'boolean') { return false }
    return !value }
function decodeURLComponent (str) { return decodeURIComponent(str) }
function base64Encode (str) { return Buffer.from(str).toString('base64') }
function base64Decode (str) { return Buffer.from(str, 'base64').toString() }
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

print("-- empty, notEmpty, length, lower, upper, reverse --");
if (!!(empty("") && notEmpty("234"))) {
    print(length("123"));
}
if ((lower("Tdd4gh") == "tdd4gh")) {
    print(upper("test"));
}
print(reverse("spinner"));
print("");
print("-- encodeURLComponent, decodeURLComponent --");
print(encodeURLComponent("http://www.google.com"));
print(encodeURLComponent("tom & jerry"));
print(decodeURLComponent(encodeURLComponent("http://www.google.com")));
print(decodeURLComponent(encodeURLComponent("tom & jerry")));
print("");
print("-- base64Encode, base64Decode --");
print(base64Encode("http://www.google.com"));
print(base64Encode("tom & jerry"));
print(base64Decode(base64Encode("http://www.google.com")));
print(base64Decode(base64Encode("tom & jerry")));
print("");
print("-- empty --");
print(empty(null));
print(empty(0));
print(empty(1));
print(empty(-1));
print(empty(0.0));
print(empty(0.01));
print(empty(""));
print(empty("string"));
print(empty("0"));
print(empty([]));
print(empty({}));
print(empty(tuple()));
print(empty(tuple(0)));
print(empty(tuple(1, 2)));
print(empty(true));
print(empty(false));
print("");
print("-- notEmpty --");
print(notEmpty(null));
print(notEmpty(0));
print(notEmpty(1));
print(notEmpty(-1));
print(notEmpty(0.0));
print(notEmpty(0.01));
print(notEmpty(""));
print(notEmpty("string"));
print(notEmpty("0"));
print(notEmpty([]));
print(notEmpty({}));
print(notEmpty(tuple()));
print(notEmpty(tuple(0)));
print(notEmpty(tuple(1, 2)));
print(notEmpty(true));
print(notEmpty(false));
print("");
print("-- replaceAll, replaceOne --");
print(replaceAll("hello world", "l", "L"));
print(replaceOne("hello world", "l", "L"));
print("");
print("-- generateUUIDv4 --");
print(length(generateUUIDv4()));
