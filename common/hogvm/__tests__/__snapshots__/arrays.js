function print (...args) { console.log(...args.map(__printHogStringOutput)) }
function indexOf (arrOrString, elem) { if (Array.isArray(arrOrString)) { return arrOrString.indexOf(elem) + 1 } else { return 0 } }
function has (arr, elem) { if (!Array.isArray(arr) || arr.length === 0) { return false } return arr.includes(elem) }
function arrayStringConcat (arr, separator = '') { if (!Array.isArray(arr)) { return '' } return arr.join(separator) }
function arraySort (arr) { if (!Array.isArray(arr)) { return [] } return [...arr].sort() }
function arrayReverseSort (arr) { if (!Array.isArray(arr)) { return [] } return [...arr].sort().reverse() }
function arrayReverse (arr) { if (!Array.isArray(arr)) { return [] } return [...arr].reverse() }
function arrayPushFront (arr, item) { if (!Array.isArray(arr)) { return [item] } return [item, ...arr] }
function arrayPushBack (arr, item) { if (!Array.isArray(arr)) { return [item] } return [...arr, item] }
function arrayPopFront (arr) { if (!Array.isArray(arr)) { return [] } return arr.slice(1) }
function arrayPopBack (arr) { if (!Array.isArray(arr)) { return [] } return arr.slice(0, arr.length - 1) }
function arrayCount (func, arr) { let count = 0; for (let i = 0; i < arr.length; i++) { if (func(arr[i])) { count = count + 1 } } return count }
function __setProperty(objectOrArray, key, value) {
    if (Array.isArray(objectOrArray)) { if (key > 0) { objectOrArray[key - 1] = value } else { objectOrArray[objectOrArray.length + key] = value } }
    else { objectOrArray[key] = value }
    return objectOrArray
}
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
function __lambda (fn) { return fn }
function __isHogError(obj) {return obj && obj.__hogError__ === true}
function __isHogDateTime(obj) { return obj && obj.__hogDateTime__ === true }
function __isHogDate(obj) { return obj && obj.__hogDate__ === true }
function __getProperty(objectOrArray, key, nullish) {
    if ((nullish && !objectOrArray) || key === 0) { return null }
    if (Array.isArray(objectOrArray)) { return key > 0 ? objectOrArray[key - 1] : objectOrArray[objectOrArray.length + key] }
    else { return objectOrArray[key] }
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

print([]);
print([1, 2, 3]);
print([1, "2", 3]);
print([1, [2, 3], 4]);
print([1, [2, [3, 4]], 5]);
let a = [1, 2, 3];
print(__getProperty(a, 2, false));
print(__getProperty(a, 2, true));
print(__getProperty(a, 2, true));
print(__getProperty(a, 7, true));
print(__getProperty(a, 7, true));
print(__getProperty([1, 2, 3], 2, false));
print(__getProperty(__getProperty(__getProperty([1, [2, [3, 4]], 5], 2, false), 2, false), 2, false));
print(__getProperty(__getProperty(__getProperty([1, [2, [3, 4]], 5], 2, true), 2, true), 2, true));
print(__getProperty(__getProperty(__getProperty([1, [2, [3, 4]], 5], 2, true), 2, true), 2, true));
print(__getProperty(__getProperty(__getProperty([1, [2, [3, 4]], 5], 7, true), 4, true), 2, true));
print(__getProperty(__getProperty(__getProperty([1, [2, [3, 4]], 5], 7, true), 4, true), 2, true));
print((__getProperty(__getProperty(__getProperty([1, [2, [3, 4]], 5], 2, false), 2, false), 2, false) + 1));
print(__getProperty(__getProperty(__getProperty([1, [2, [3, 4]], 5], 2, false), 2, false), 2, false));
print("------");
let b = [1, 2, [1, 2, 3]];
__setProperty(b, 2, 4);
print(__getProperty(b, 1, false));
print(__getProperty(b, 2, false));
print(__getProperty(b, 3, false));
__setProperty(__getProperty(b, 3, false), 3, 8);
print(b);
print("------");
print(arrayPushBack([1, 2, 3], 4));
print(arrayPushFront([1, 2, 3], 0));
print(arrayPopBack([1, 2, 3]));
print(arrayPopFront([1, 2, 3]));
print(arraySort([3, 2, 1]));
print(arrayReverse([1, 2, 3]));
print(arrayReverseSort([3, 2, 1]));
print(arrayStringConcat([1, 2, 3], ","));
print("-----");
let arr = [1, 2, 3, 4];
print(arr);
arrayPushBack(arr, 5);
print(arr);
arrayPushFront(arr, 0);
print(arr);
arrayPopBack(arr);
print(arr);
arrayPopFront(arr);
print(arr);
arraySort(arr);
print(arr);
arrayReverse(arr);
print(arr);
arrayReverseSort(arr);
print(arr);
print("------");
print(has(arr, 0));
print(has(arr, 2));
print(has(arr, "banana"));
print(has("banananas", "banana"));
print(has("banananas", "foo"));
print(has(["1", "2"], "1"));
print(indexOf([1, 2, 3], 1));
print(indexOf([1, 2, 3], 2));
print(indexOf([1, 2, 3], 3));
print(indexOf([1, 2, 3], 4));
print(arrayCount(__lambda((x) => (x > 2)), [1, 2, 3, 4, 5]));
print("------");
let c = [1, 2, 3];
print(__getProperty(c, 1, false), __getProperty(c, 2, false), __getProperty(c, 3, false), __getProperty(c, 4, false));
print(__getProperty(c, -1, false), __getProperty(c, -2, false), __getProperty(c, -3, false), __getProperty(c, -4, false));
print("------");
print((["a", "b", "c"].includes("a")));
print((["a", "b", "c"].includes("d")));
print(([].includes("a")));
