function print (...args) { console.log(...args.map(__printHogStringOutput)) }
function like (str, pattern) { return __like(str, pattern, false) }
function arrayReduce (func, arr, initial) { let result = initial; for (let i = 0; i < arr.length; i++) { result = func(result, arr[i]) } return result }
function arrayMap (func, arr) { let result = []; for (let i = 0; i < arr.length; i++) { result = arrayPushBack(result, func(arr[i])) } return result }
function arrayFilter (func, arr) { let result = []; for (let i = 0; i < arr.length; i++) { if (func(arr[i])) { result = arrayPushBack(result, arr[i]) } } return result}
function arrayPushBack (arr, item) { if (!Array.isArray(arr)) { return [item] } return [...arr, item] }
function arrayExists (func, arr) { for (let i = 0; i < arr.length; i++) { if (func(arr[i])) { return true } } return false }
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
function __lambda (fn) { return fn }
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

print("--- arrayMap ----");
print(arrayMap(__lambda((x) => (x * 2)), [1, 2, 3]));
print("--- arrayExists ----");
print(arrayExists(__lambda((x) => like(x, "%nana%")), ["apple", "banana", "cherry"]));
print(arrayExists(__lambda((x) => like(x, "%boom%")), ["apple", "banana", "cherry"]));
print(arrayExists(__lambda((x) => like(x, "%boom%")), []));
print("--- arrayFilter ----");
print(arrayFilter(__lambda((x) => like(x, "%nana%")), ["apple", "banana", "cherry"]));
print(arrayFilter(__lambda((x) => like(x, "%e%")), ["apple", "banana", "cherry"]));
print(arrayFilter(__lambda((x) => like(x, "%boom%")), []));
print("--- arrayReduce ----");
print(arrayReduce(__lambda((a, b) => (a + b)), [1, 2, 3, 4, 5], 0));
print(arrayReduce(__lambda((a, b) => (a + b)), [1, 2, 3, 4, 5], 15));
print(arrayReduce(__lambda((a, b) => (a - b)), [5, 10], 30));
