function __x_Error (message, payload) {
    return __newHogError('Error', message, payload)
}

function print (...args) {
    console.log(...args.map(__printHogStringOutput))
}

function __newHogError(type, message, payload) {
    let error = new Error(message || 'An error occurred');
    error.__hogError__ = true
    error.type = type
    error.payload = payload
    return error
}

function concat (...args) {
    return args.map((arg) => (arg === null ? '' : __STLToString([arg]))).join('')
}

function __STLToString(args) {
    if (__isHogDate(args[0])) {
        const month = args[0].month
        const day = args[0].day
        return `\${args[0].year}-\${month < 10 ? '0' : ''}\${month}-\${day < 10 ? '0' : ''}\${day}`
    }
    if (__isHogDateTime(args[0])) {
        return DateTime.fromSeconds(args[0].dt, { zone: args[0].zone }).toISO()
    }
    return __printHogStringOutput(args[0])
}

function __printHogStringOutput(obj) {
    if (typeof obj === 'string') {
        return obj
    }
    return __printHogValue(obj)
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

function __isHogCallable(obj) {
    return obj && typeof obj === 'function' && obj.__isHogCallable__
}

function __isHogClosure(obj) {
    return obj && obj.__isHogClosure__ === true
}

function __isHogError(obj) {
    return obj && obj.__hogError__ === true
}

function __isHogDateTime(obj) {
    return obj && obj.__hogDateTime__ === true
}

function __isHogDate(obj) {
    return obj && obj.__hogDate__ === true
}

print("start");
try {
    print("try");
} catch (__error) { if (true) { let e = __error;
print(concat(e, " was the exception"));
}
}
print("------------------");
print("start");
try {
    print("try");
} catch (__error) { if (true) { let e = __error;
print("No var for error, but no error");
}
}
print("------------------");
try {
    print("try again");
    throw __x_Error();
} catch (__error) { if (true) { let e = __error;
print(concat(e, " was the exception"));
}
}
print("------------------");
try {
    print("try again");
    throw __x_Error();
} catch (__error) { if (true) { let e = __error;
print("No var for error");
}
}
print("------------------");
function third() {
    print("Throwing in third");
    throw __x_Error("Threw in third");
}
function second() {
    print("second");
    third();
}
function first() {
    print("first");
    second();
}
function base() {
    print("base");
    try {
            first();
        } catch (__error) { if (true) { let e = __error;
        print(concat("Caught in base: ", e));    throw e;
    }
    }
}
try {
    base();
} catch (__error) { if (true) { let e = __error;
print(concat("Caught in root: ", e));
}
}
print("The end");
