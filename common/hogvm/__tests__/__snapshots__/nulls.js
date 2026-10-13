function values (obj) { if (typeof obj === 'object' && obj !== null) { if (Array.isArray(obj)) { return [...obj] } else if (obj instanceof Map) { return Array.from(obj.values()) } return Object.values(obj) } return [] }
function upper (value) { return value === null || value === undefined ? null : value.toUpperCase() }
function trimRight (str, char) {
    if (str === null || str === undefined) {
        return null
    }
    if (char === null || char === undefined) {
        char = ' '
    }
    if (char.length !== 1) {
        return ''
    }
    let end = str.length
    while (str[end - 1] === char) {
        end--
    }
    return str.slice(0, end)
}
function trimLeft (str, char) {
    if (str === null || str === undefined) {
        return null
    }
    if (char === null || char === undefined) {
        char = ' '
    }
    if (char.length !== 1) {
        return ''
    }
    let start = 0
    while (str[start] === char) {
        start++
    }
    return str.slice(start)
}
function trim (str, char) {
    if (str === null || str === undefined) {
        return null
    }
    if (char === null || char === undefined) {
        char = ' '
    }
    if (char.length !== 1) {
        return ''
    }
    let start = 0
    while (str[start] === char) {
        start++
    }
    let end = str.length
    while (str[end - 1] === char) {
        end--
    }
    if (start >= end) {
        return ''
    }
    return str.slice(start, end)
}
function splitByString (separator, str, maxSplits) { if (str === null || str === undefined) { return null } if (maxSplits === undefined || maxSplits === null) { return str.split(separator) } return str.split(separator, maxSplits) }
function reverse (value) { return value === null || value === undefined ? null : value.split('').reverse().join('') }
function replaceOne (str, searchValue, replaceValue) { return str === null || str === undefined ? null : str.replace(searchValue, replaceValue) }
function replaceAll (str, searchValue, replaceValue) { return str === null || str === undefined ? null : str.replaceAll(searchValue, replaceValue) }
function print (...args) { console.log(...args.map(__printHogStringOutput)) }
function match (str, pattern) { return !str || !pattern ? false : new RegExp(pattern).test(str) }
function lessOrEquals(a, b) { return a !== null && a !== undefined && b !== null && b !== undefined && a <= b }
function less(a, b) { return a !== null && a !== undefined && b !== null && b !== undefined && a < b }
function length (value) { return value === null || value === undefined ? null : value.length }
function keys (obj) { if (typeof obj === 'object' && obj !== null) { if (Array.isArray(obj)) { return Array.from(obj.keys()) } else if (obj instanceof Map) { return Array.from(obj.keys()) } return Object.keys(obj) } return [] }
function greaterOrEquals(a, b) { return a !== null && a !== undefined && b !== null && b !== undefined && a >= b }
function greater(a, b) { return a !== null && a !== undefined && b !== null && b !== undefined && a > b }
function arrayStringConcat (arr, separator = '') { if (!Array.isArray(arr)) { return '' } return arr.join(separator) }
function arrayReduce (func, arr, initial) { let result = initial; for (let i = 0; i < (arr ?? []).length; i++) { result = func(result, arr[i]) } return result }
function arrayPopFront (arr) { if (!Array.isArray(arr)) { return [] } return arr.slice(1) }
function arrayMap (func, arr) { let result = []; for (let i = 0; i < (arr ?? []).length; i++) { result = arrayPushBack(result, func(arr[i])) } return result }
function arrayFilter (func, arr) { let result = []; for (let i = 0; i < (arr ?? []).length; i++) { if (func(arr[i])) { result = arrayPushBack(result, arr[i]) } } return result}
function arrayPushBack (arr, item) { if (!Array.isArray(arr)) { return [item] } return [...arr, item] }
function arrayExists (func, arr) { for (let i = 0; i < (arr ?? []).length; i++) { if (func(arr[i])) { return true } } return false }
function arrayCount (func, arr) { let count = 0; for (let i = 0; i < (arr ?? []).length; i++) { if (func(arr[i])) { count = count + 1 } } return count }
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
function __lte (a, b) { return a === null || a === undefined || b === null || b === undefined ? false : a <= b }
function __lt (a, b) { return a === null || a === undefined || b === null || b === undefined ? false : a < b }
function __lambda (fn) { return fn }
function __isHogError(obj) {return obj && obj.__hogError__ === true}
function __isHogDateTime(obj) { return obj && obj.__hogDateTime__ === true }
function __isHogDate(obj) { return obj && obj.__hogDate__ === true }
function __gte (a, b) { return a === null || a === undefined || b === null || b === undefined ? false : a >= b }
function __gt (a, b) { return a === null || a === undefined || b === null || b === undefined ? false : a > b }
function __escapeString(value) {
    const singlequoteEscapeCharsMap = { '\b': '\\b', '\f': '\\f', '\r': '\\r', '\n': '\\n', '\t': '\\t', '\0': '\\0', '\v': '\\v', '\\': '\\\\', "'": "\\'" }
    return `'${value.split('').map((c) => singlequoteEscapeCharsMap[c] || c).join('')}'`;
}
function __escapeIdentifier(identifier) {
    const backquoteEscapeCharsMap = { '\b': '\\b', '\f': '\\f', '\r': '\\r', '\n': '\\n', '\t': '\\t', '\0': '\\0', '\v': '\\v', '\\': '\\\\', '`': '``' }
    if (typeof identifier === 'number') return identifier.toString();
    if (/^[A-Za-z_$][A-Za-z0-9_$]*$/.test(identifier)) return identifier;
    return `\`${identifier.split('').map((c) => backquoteEscapeCharsMap[c] || c).join('')}\``;
}

print("-- match --");
print(match("uu", "u"));
print(match("uu", "b"));
print(match(null, "u"));
print(match(null, "b"));
print(match("uu", null));
print(match("null", null));
print(match("uu", "u"));
print(match("uu", "b"));
print(match(null, "u"));
print(match(null, "b"));
print(match("uu", null));
print(match("null", null));
print("-- string and array functions on null --");
print(length(null));
print(upper(null));
print(reverse(null));
print(replaceOne(null, "a", "b"));
print(replaceAll(null, "a", "b"));
print(trim(null));
print(trimLeft(null));
print(trimRight(null));
print(keys(null));
print(values(null));
print(arrayExists(__lambda((x) => (x == "a")), null));
print(arrayMap(__lambda((x) => x), null));
print(arrayFilter(__lambda((x) => (x == "a")), null));
print(arrayCount(__lambda((x) => (x == "a")), null));
print(arrayReduce(__lambda((acc, x) => (acc + x)), null, 0));
print(splitByString(" ", null));
print(arrayStringConcat(arrayPopFront(splitByString(" ", null)), " "));
print((0 == null));
print((0 != null));
print((() => { const expr=(0), low=(1), high=(10); return expr !== null && expr !== undefined && low !== null && low !== undefined && high !== null && high !== undefined && !!(expr < 1 || expr > 10); })());
print(__gt(length(null), 3));
print(__lt(length(null), 3));
print(__lt(null, 3));
print(__lte(null, 0));
print(__gt(null, 3));
print(__gte(null, 0));
print(__gt(3, null));
print(__gt(null, null));
print((!__gt(length(null), 3)));
print((length(null) == 0));
print(less(null, 3));
print(greater(3, null));
print(lessOrEquals(null, null));
print(greaterOrEquals(null, 0));
print(less(1, 3));
