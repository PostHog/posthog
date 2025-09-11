function print (...args) { console.log(...args.map(__printHogStringOutput)) }
function empty (value) {
    if (typeof value === 'object') {
        if (Array.isArray(value)) { return value.length === 0 } else if (value === null) { return true } else if (value instanceof Map) { return value.size === 0 }
        return Object.keys(value).length === 0
    } else if (typeof value === 'number' || typeof value === 'boolean') { return false }
    return !value }
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

print("-- test functions --");
function add(a, b) {
    return (a + b);
}
print(add);
function add2(a, b) {
    let c = (a + b);
    return c;
}
print(add2);
function mult(a, b) {
    return (a * b);
}
print(mult);
function noArgs() {
    let url = "basdfasdf";
    let second = (2 + 3);
    return second;
}
print(noArgs);
function empty() {

}
function empty2() {

}
function empty3() {

}
function noReturn() {
    let a = 1;
    let b = 2;
    let c = (a + b);
}
function emptyReturn() {
    return null;
}
function emptyReturnBeforeOtherStuff() {
    return null;
    (2 + 2);
}
function emptyReturnBeforeOtherStuffNoSemicolon() {
    return (2 + 2);
}
function ifThenReturn() {
    if (false) {
            return null;
        }
    return 4;
}
print(add(3, 4));
print(((add(3, 4) + 100) + add(1, 1)));
print((noArgs() ?? -1));
print((empty() ?? -1));
print((empty2() ?? -1));
print((empty3() ?? -1));
print((noReturn() ?? -1));
print((emptyReturn() ?? -1));
print((emptyReturnBeforeOtherStuff() ?? -1));
print((emptyReturnBeforeOtherStuffNoSemicolon() ?? -1));
print((ifThenReturn() ?? -1));
print(mult(((add(3, 4) + 100) + add(2, 1)), 2));
print(mult(((add2(3, 4) + 100) + add2(2, 1)), 10));
function printArgs(arg1, arg2, arg3, arg4, arg5, arg6, arg7) {
    print(arg1, arg2, arg3, arg4, arg5, arg6, arg7);
}
let printArgs2 = __lambda((arg1, arg2, arg3, arg4, arg5, arg6, arg7) => {
    print(arg1, arg2, arg3, arg4, arg5, arg6, arg7);
    return null;
});
printArgs(1, 2, 3, 4, 5, 6, 7);
printArgs2(1, 2, 3, 4, 5, 6, 7);
printArgs(1, 2, 3, 4, 5, 6);
printArgs2(1, 2, 3, 4, 5, 6);
printArgs(1, 2, 3, 4, 5);
printArgs2(1, 2, 3, 4, 5);
printArgs();
printArgs2();
