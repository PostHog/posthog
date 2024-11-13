function arrayPushFront (arr, item) {
    if (!Array.isArray(arr)) {
        return [item]
    }
    return [item, ...arr]
}

function arrayReverse (arr) {
    if (!Array.isArray(arr)) {
        return []
    }
    return [...arr].reverse()
}

function has (arr, elem) {
    if (!Array.isArray(arr) || arr.length === 0) {
        return false
    }
    return arr.includes(elem)
}

function arraySort (arr) {
    if (!Array.isArray(arr)) {
        return []
    }
    return [...arr].sort()
}

function arrayReverseSort (arr) {
    if (!Array.isArray(arr)) {
        return []
    }
    return [...arr].sort().reverse()
}

function print (...args) {
    console.log(...args.map(__printHogStringOutput))
}

function __printHogStringOutput(obj) {
    if (typeof obj === 'string') {
        return obj
    }
    return __printHogValue(obj)
}

function arrayCount (func, arr) {
    let count = 0
    for (let i = 0; i < arr.length; i++) {
        if (func(arr[i])) {
            count = count + 1
        }
    }
    return count
}

function indexOf (arrOrString, elem) {
    if (Array.isArray(arrOrString)) {
        return arrOrString.indexOf(elem) + 1
    } else {
        return 0
    }
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

function __isHogDate(obj) {
    return obj && obj.__hogDate__ === true
}

function arrayPopFront (arr) {
    if (!Array.isArray(arr)) {
        return []
    }
    return arr.slice(1)
}

function arrayStringConcat (arr, separator = '') {
    if (!Array.isArray(arr)) {
        return ''
    }
    return arr.join(separator)
}

function __isHogDateTime(obj) {
    return obj && obj.__hogDateTime__ === true
}

function arrayPushBack (arr, item) {
    if (!Array.isArray(arr)) {
        return [item]
    }
    return [...arr, item]
}

function arrayPopBack (arr) {
    if (!Array.isArray(arr)) {
        return []
    }
    return arr.slice(0, arr.length - 1)
}print([]);
print([1, 2, 3]);
print([1, "2", 3]);
print([1, [2, 3], 4]);
print([1, [2, [3, 4]], 5]);
let a = [1, 2, 3];
print(a[((2) > 0 ? (2 - 1) : ((a).length + (2)))]);
print((a?.[((2) > 0 ? (2 - 1) : ((a).length + (2)))]));
print((a?.[((2) > 0 ? (2 - 1) : ((a).length + (2)))]));
print((a?.[((7) > 0 ? (7 - 1) : ((a).length + (7)))]));
print((a?.[((7) > 0 ? (7 - 1) : ((a).length + (7)))]));
print([1, 2, 3][((2) > 0 ? (2 - 1) : (([1, 2, 3]).length + (2)))]);
print([1, [2, [3, 4]], 5][((2) > 0 ? (2 - 1) : (([1, [2, [3, 4]], 5]).length + (2)))][((2) > 0 ? (2 - 1) : (([1, [2, [3, 4]], 5][((2) > 0 ? (2 - 1) : (([1, [2, [3, 4]], 5]).length + (2)))]).length + (2)))][((2) > 0 ? (2 - 1) : (([1, [2, [3, 4]], 5][((2) > 0 ? (2 - 1) : (([1, [2, [3, 4]], 5]).length + (2)))][((2) > 0 ? (2 - 1) : (([1, [2, [3, 4]], 5][((2) > 0 ? (2 - 1) : (([1, [2, [3, 4]], 5]).length + (2)))]).length + (2)))]).length + (2)))]);
print(((([1, [2, [3, 4]], 5]?.[((2) > 0 ? (2 - 1) : (([1, [2, [3, 4]], 5]).length + (2)))])?.[((2) > 0 ? (2 - 1) : ((([1, [2, [3, 4]], 5]?.[((2) > 0 ? (2 - 1) : (([1, [2, [3, 4]], 5]).length + (2)))])).length + (2)))])?.[((2) > 0 ? (2 - 1) : (((([1, [2, [3, 4]], 5]?.[((2) > 0 ? (2 - 1) : (([1, [2, [3, 4]], 5]).length + (2)))])?.[((2) > 0 ? (2 - 1) : ((([1, [2, [3, 4]], 5]?.[((2) > 0 ? (2 - 1) : (([1, [2, [3, 4]], 5]).length + (2)))])).length + (2)))])).length + (2)))]));
print(((([1, [2, [3, 4]], 5]?.[((2) > 0 ? (2 - 1) : (([1, [2, [3, 4]], 5]).length + (2)))])?.[((2) > 0 ? (2 - 1) : ((([1, [2, [3, 4]], 5]?.[((2) > 0 ? (2 - 1) : (([1, [2, [3, 4]], 5]).length + (2)))])).length + (2)))])?.[((2) > 0 ? (2 - 1) : (((([1, [2, [3, 4]], 5]?.[((2) > 0 ? (2 - 1) : (([1, [2, [3, 4]], 5]).length + (2)))])?.[((2) > 0 ? (2 - 1) : ((([1, [2, [3, 4]], 5]?.[((2) > 0 ? (2 - 1) : (([1, [2, [3, 4]], 5]).length + (2)))])).length + (2)))])).length + (2)))]));
print(((([1, [2, [3, 4]], 5]?.[((7) > 0 ? (7 - 1) : (([1, [2, [3, 4]], 5]).length + (7)))])?.[((4) > 0 ? (4 - 1) : ((([1, [2, [3, 4]], 5]?.[((7) > 0 ? (7 - 1) : (([1, [2, [3, 4]], 5]).length + (7)))])).length + (4)))])?.[((2) > 0 ? (2 - 1) : (((([1, [2, [3, 4]], 5]?.[((7) > 0 ? (7 - 1) : (([1, [2, [3, 4]], 5]).length + (7)))])?.[((4) > 0 ? (4 - 1) : ((([1, [2, [3, 4]], 5]?.[((7) > 0 ? (7 - 1) : (([1, [2, [3, 4]], 5]).length + (7)))])).length + (4)))])).length + (2)))]));
print(((([1, [2, [3, 4]], 5]?.[((7) > 0 ? (7 - 1) : (([1, [2, [3, 4]], 5]).length + (7)))])?.[((4) > 0 ? (4 - 1) : ((([1, [2, [3, 4]], 5]?.[((7) > 0 ? (7 - 1) : (([1, [2, [3, 4]], 5]).length + (7)))])).length + (4)))])?.[((2) > 0 ? (2 - 1) : (((([1, [2, [3, 4]], 5]?.[((7) > 0 ? (7 - 1) : (([1, [2, [3, 4]], 5]).length + (7)))])?.[((4) > 0 ? (4 - 1) : ((([1, [2, [3, 4]], 5]?.[((7) > 0 ? (7 - 1) : (([1, [2, [3, 4]], 5]).length + (7)))])).length + (4)))])).length + (2)))]));
print(([1, [2, [3, 4]], 5][((2) > 0 ? (2 - 1) : (([1, [2, [3, 4]], 5]).length + (2)))][((2) > 0 ? (2 - 1) : (([1, [2, [3, 4]], 5][((2) > 0 ? (2 - 1) : (([1, [2, [3, 4]], 5]).length + (2)))]).length + (2)))][((2) > 0 ? (2 - 1) : (([1, [2, [3, 4]], 5][((2) > 0 ? (2 - 1) : (([1, [2, [3, 4]], 5]).length + (2)))][((2) > 0 ? (2 - 1) : (([1, [2, [3, 4]], 5][((2) > 0 ? (2 - 1) : (([1, [2, [3, 4]], 5]).length + (2)))]).length + (2)))]).length + (2)))] + 1));
print([1, [2, [3, 4]], 5][((2) > 0 ? (2 - 1) : (([1, [2, [3, 4]], 5]).length + (2)))][((2) > 0 ? (2 - 1) : (([1, [2, [3, 4]], 5][((2) > 0 ? (2 - 1) : (([1, [2, [3, 4]], 5]).length + (2)))]).length + (2)))][((2) > 0 ? (2 - 1) : (([1, [2, [3, 4]], 5][((2) > 0 ? (2 - 1) : (([1, [2, [3, 4]], 5]).length + (2)))][((2) > 0 ? (2 - 1) : (([1, [2, [3, 4]], 5][((2) > 0 ? (2 - 1) : (([1, [2, [3, 4]], 5]).length + (2)))]).length + (2)))]).length + (2)))]);
print("------");
let b = [1, 2, [1, 2, 3]];
b[((2) > 0 ? (2 - 1) : ((b).length + (2)))] = 4;
print(b[((1) > 0 ? (1 - 1) : ((b).length + (1)))]);
print(b[((2) > 0 ? (2 - 1) : ((b).length + (2)))]);
print(b[((3) > 0 ? (3 - 1) : ((b).length + (3)))]);
b[((3) > 0 ? (3 - 1) : ((b).length + (3)))][((3) > 0 ? (3 - 1) : ((b[((3) > 0 ? (3 - 1) : ((b).length + (3)))]).length + (3)))] = 8;
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
print(arrayCount((x) => (x > 2), [1, 2, 3, 4, 5]));
print("------");
let c = [1, 2, 3];
print(c[((1) > 0 ? (1 - 1) : ((c).length + (1)))], c[((2) > 0 ? (2 - 1) : ((c).length + (2)))], c[((3) > 0 ? (3 - 1) : ((c).length + (3)))], c[((4) > 0 ? (4 - 1) : ((c).length + (4)))]);
print(c[((-1) > 0 ? (-1 - 1) : ((c).length + (-1)))], c[((-2) > 0 ? (-2 - 1) : ((c).length + (-2)))], c[((-3) > 0 ? (-3 - 1) : ((c).length + (-3)))], c[((-4) > 0 ? (-4 - 1) : ((c).length + (-4)))]);
