function print (...args) {
    console.log(...args.map(__printHogStringOutput))
}

function like (str, pattern) {
    return __like(str, pattern, false)
}

function match (str, pattern) {
   return new RegExp(pattern).test(str)
}

function concat (...args) {
    return args.map((arg) => (arg === null ? '' : __STLToString([arg]))).join('')
}

function toUUID (value) {
    return __STLToString([value])
}

function toInt (value) {
    if (__isHogDateTime(value)) {
        return Math.floor(value.dt)
    } else if (__isHogDate(value)) {
        const day = DateTime.fromObject({ year: value.year, month: value.month, day: value.day })
        const epoch = DateTime.fromObject({ year: 1970, month: 1, day: 1 })
        return Math.floor(day.diff(epoch, 'days').days)
    }
    return !isNaN(parseInt(value)) ? parseInt(value) : null
}

function toFloat (value) {
    if (__isHogDateTime(value)) {
        return value.dt
    } else if (__isHogDate(value)) {
        const day = DateTime.fromObject({ year: value.year, month: value.month, day: value.day })
        const epoch = DateTime.fromObject({ year: 1970, month: 1, day: 1 })
        return Math.floor(day.diff(epoch, 'days').days)
    }
    return !isNaN(parseFloat(value)) ? parseFloat(value) : null
}

function ilike (str, pattern) {
    return __like(str, pattern, true)
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

function toString (value) {
    return __STLToString([value])
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

function jsonStringify (value, spacing) {
    function convert(x, marked) {
        if (!marked) {
            marked = new Set()
        }
        if (typeof x === 'object' && x !== null) {
            if (marked.has(x)) {
                return null
            }
            marked.add(x)
            try {
                if (x instanceof Map) {
                    const obj = {}
                    x.forEach((value, key) => {
                        obj[convert(key, marked)] = convert(value, marked)
                    })
                    return obj
                }
                if (Array.isArray(x)) {
                    return x.map((v) => convert(v, marked))
                }
                if (__isHogDateTime(x) || __isHogDate(x) || __isHogError(x)) {
                    return x
                }
                if (__isHogCallable(x) || __isHogClosure(x)) {
                    const callable = __isHogCallable(x) ? x : x.callable
                    return `fn<${callable.name || 'lambda'}(${callable.argCount})>`
                }
                const obj = {}
                for (const key in x) {
                    obj[key] = convert(x[key], marked)
                }
                return obj
            } finally {
                marked.delete(x)
            }
        }
        return x
    }
    if (spacing && typeof spacing === 'number' && spacing > 0) {
        return JSON.stringify(convert(value), null, spacing)
    }
    return JSON.stringify(convert(value))
}

function __isHogClosure(obj) {
    return obj && obj.__isHogClosure__ === true
}

function __isHogCallable(obj) {
    return obj && typeof obj === 'function' && obj.__isHogCallable__
}

function __isHogError(obj) {
    return obj && obj.__hogError__ === true
}

function __isHogDate(obj) {
    return obj && obj.__hogDate__ === true
}

function __isHogDateTime(obj) {
    return obj && obj.__hogDateTime__ === true
}

function test(val) {
    print(jsonStringify(val));
}
print("-- test the most common expressions --");
test((1 + 2));
test((1 - 2));
test((3 * 2));
test((3 / 2));
test((3 % 2));
test(!!(1 && 2));
test(!!(1 || 0));
test(!!(1 && 0));
test(!!(1 || !!(0 && 1) || 2));
test(!!(1 && 0 && 1));
test(!!(!!(1 || 2) && !!(1 || 2)));
test(true);
test((!true));
test(false);
test(null);
test(3.14);
test((1 == 2));
test((1 == 2));
test((1 != 2));
test((1 < 2));
test((1 <= 2));
test((1 > 2));
test((1 >= 2));
test(like("a", "b"));
test(like("baa", "%a%"));
test(like("baa", "%x%"));
test(ilike("baa", "%A%"));
test(ilike("baa", "%C%"));
test(ilike("a", "b"));
test(!like("a", "b"));
test(!ilike("a", "b"));
test(("car".includes("a")));
test(("foo".includes("a")));
test((!"car".includes("a")));
test(concat("arg", "another"));
test(concat(1, null));
test(concat(true, false));
test(match("test", "e.*"));
test(match("test", "^e.*"));
test(match("test", "x.*"));
test(new RegExp("e.*").test("test"));
test(!(new RegExp("e.*").test("test")));
test(new RegExp("^e.*").test("test"));
test(!(new RegExp("^e.*").test("test")));
test(new RegExp("x.*").test("test"));
test(!(new RegExp("x.*").test("test")));
test(new RegExp("EST", "i").test("test"));
test(new RegExp("EST", "i").test("test"));
test(!(new RegExp("EST", "i").test("test")));
test(toString(1));
test(toString(1.5));
test(toString(true));
test(toString(null));
test(toString("string"));
test(toInt("1"));
test(toInt("bla"));
test(toFloat("1.2"));
test(toFloat("bla"));
test(toUUID("asd"));
test((1 == null));
test((1 != null));
test(("1" == 1));
test((1 == "1"));
test((1 == true));
test((0 == true));
test((2 == true));
test((1 != false));
test((1 == "2"));
test((1 == "2"));
test((1 != "2"));
test((1 < "2"));
test((1 <= "2"));
test((1 > "2"));
test((1 >= "2"));
test(("1" == 2));
test(("1" == 2));
test(("1" != 2));
test(("1" < 2));
test(("1" <= 2));
test(("1" > 2));
test(("1" >= 2));
