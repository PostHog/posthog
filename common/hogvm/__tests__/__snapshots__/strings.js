function trimRight (str, char) {
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
function splitByString (separator, str, maxSplits) { if (maxSplits === undefined || maxSplits === null) { return str.split(separator) } return str.split(separator, maxSplits) }
function print (...args) { console.log(...args.map(__printHogStringOutput)) }
function positionCaseInsensitive (str, elem) { if (typeof str === 'string') { return str.toLowerCase().indexOf(String(elem).toLowerCase()) + 1 } else { return 0 } }
function position (str, elem) { if (typeof str === 'string') { return str.indexOf(String(elem)) + 1 } else { return 0 } }
function notLike (str, pattern) { return !__like(str, pattern, false) }
function notILike (str, pattern) { return !__like(str, pattern, true) }
function like (str, pattern) { return __like(str, pattern, false) }
function ilike (str, pattern) { return __like(str, pattern, true) }
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

print(trim("  hello  world  "));
print(trimLeft("  hello world  "));
print(trimRight("  hello world  "));
print(trim("xxxx  hello  world  xx", "x"));
print(trimLeft("xxxx  hello  world  xx", "x"));
print(trimRight("xxxx  hello  world  xx", "x"));
print(splitByString(" ", "hello world and more"));
print(splitByString(" ", "hello world and more", 1));
print(splitByString(" ", "hello world and more", 2));
print(splitByString(" ", "hello world and more", 10));
print(like("banana", "N"));
print(like("banana", "n"));
print(like("banana", "naan"));
print(ilike("banana", "N"));
print(ilike("banana", "n"));
print(ilike("banana", "naan"));
print(notLike("banana", "N"));
print(notILike("banana", "NO"));
print(position("abc", "a"));
print(position("abc", "b"));
print(position("abc", "c"));
print(position("abc", "d"));
print(positionCaseInsensitive("AbC", "a"));
print(positionCaseInsensitive("AbC", "b"));
print(positionCaseInsensitive("AbC", "c"));
print(positionCaseInsensitive("AbC", "d"));
