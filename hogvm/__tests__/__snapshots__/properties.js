function print (...args) {
    console.log(...args.map(__printHogStringOutput))
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

function __isHogDateTime(obj) {
    return obj && obj.__hogDateTime__ === true
}{
    let r = [1, 2, {"d": [1, 3, 42, 6]}];
    print(r[((3) > 0 ? (3 - 1) : ((r).length + (3)))][(("d") > 0 ? ("d" - 1) : ((r[((3) > 0 ? (3 - 1) : ((r).length + (3)))]).length + ("d")))][((2) > 0 ? (2 - 1) : ((r[((3) > 0 ? (3 - 1) : ((r).length + (3)))][(("d") > 0 ? ("d" - 1) : ((r[((3) > 0 ? (3 - 1) : ((r).length + (3)))]).length + ("d")))]).length + (2)))]);
}
{
    let r = [1, 2, {"d": [1, 3, 42, 6]}];
    print(r[((3) > 0 ? (3 - 1) : ((r).length + (3)))][(("d") > 0 ? ("d" - 1) : ((r[((3) > 0 ? (3 - 1) : ((r).length + (3)))]).length + ("d")))][((3) > 0 ? (3 - 1) : ((r[((3) > 0 ? (3 - 1) : ((r).length + (3)))][(("d") > 0 ? ("d" - 1) : ((r[((3) > 0 ? (3 - 1) : ((r).length + (3)))]).length + ("d")))]).length + (3)))]);
}
{
    let r = [1, 2, {"d": [1, 3, 42, 6]}];
    print(r[((3) > 0 ? (3 - 1) : ((r).length + (3)))][(("d") > 0 ? ("d" - 1) : ((r[((3) > 0 ? (3 - 1) : ((r).length + (3)))]).length + ("d")))][((4) > 0 ? (4 - 1) : ((r[((3) > 0 ? (3 - 1) : ((r).length + (3)))][(("d") > 0 ? ("d" - 1) : ((r[((3) > 0 ? (3 - 1) : ((r).length + (3)))]).length + ("d")))]).length + (4)))]);
}
{
    let r = {"d": [1, 3, 42, 6]};
    print(r.d[((2) > 0 ? (2 - 1) : ((r.d).length + (2)))]);
}
{
    let r = [1, 2, {"d": [1, 3, 42, 3]}];
    r[((3) > 0 ? (3 - 1) : ((r).length + (3)))][(("d") > 0 ? ("d" - 1) : ((r[((3) > 0 ? (3 - 1) : ((r).length + (3)))]).length + ("d")))][((3) > 0 ? (3 - 1) : ((r[((3) > 0 ? (3 - 1) : ((r).length + (3)))][(("d") > 0 ? ("d" - 1) : ((r[((3) > 0 ? (3 - 1) : ((r).length + (3)))]).length + ("d")))]).length + (3)))] = 3;
    print(r[((3) > 0 ? (3 - 1) : ((r).length + (3)))][(("d") > 0 ? ("d" - 1) : ((r[((3) > 0 ? (3 - 1) : ((r).length + (3)))]).length + ("d")))][((3) > 0 ? (3 - 1) : ((r[((3) > 0 ? (3 - 1) : ((r).length + (3)))][(("d") > 0 ? ("d" - 1) : ((r[((3) > 0 ? (3 - 1) : ((r).length + (3)))]).length + ("d")))]).length + (3)))]);
}
{
    let r = [1, 2, {"d": [1, 3, 42, 3]}];
    r[((3) > 0 ? (3 - 1) : ((r).length + (3)))][(("d") > 0 ? ("d" - 1) : ((r[((3) > 0 ? (3 - 1) : ((r).length + (3)))]).length + ("d")))][((3) > 0 ? (3 - 1) : ((r[((3) > 0 ? (3 - 1) : ((r).length + (3)))][(("d") > 0 ? ("d" - 1) : ((r[((3) > 0 ? (3 - 1) : ((r).length + (3)))]).length + ("d")))]).length + (3)))] = 3;
    print(r[((3) > 0 ? (3 - 1) : ((r).length + (3)))][(("d") > 0 ? ("d" - 1) : ((r[((3) > 0 ? (3 - 1) : ((r).length + (3)))]).length + ("d")))][((3) > 0 ? (3 - 1) : ((r[((3) > 0 ? (3 - 1) : ((r).length + (3)))][(("d") > 0 ? ("d" - 1) : ((r[((3) > 0 ? (3 - 1) : ((r).length + (3)))]).length + ("d")))]).length + (3)))]);
}
{
    let r = [1, 2, {"d": [1, 3, 42, 3]}];
    r[((3) > 0 ? (3 - 1) : ((r).length + (3)))][(("c") > 0 ? ("c" - 1) : ((r[((3) > 0 ? (3 - 1) : ((r).length + (3)))]).length + ("c")))] = [666];
    print(r[((3) > 0 ? (3 - 1) : ((r).length + (3)))]);
}
{
    let r = [1, 2, {"d": [1, 3, 42, 3]}];
    r[((3) > 0 ? (3 - 1) : ((r).length + (3)))][(("d") > 0 ? ("d" - 1) : ((r[((3) > 0 ? (3 - 1) : ((r).length + (3)))]).length + ("d")))][((3) > 0 ? (3 - 1) : ((r[((3) > 0 ? (3 - 1) : ((r).length + (3)))][(("d") > 0 ? ("d" - 1) : ((r[((3) > 0 ? (3 - 1) : ((r).length + (3)))]).length + ("d")))]).length + (3)))] = 3;
    print(r[((3) > 0 ? (3 - 1) : ((r).length + (3)))][(("d") > 0 ? ("d" - 1) : ((r[((3) > 0 ? (3 - 1) : ((r).length + (3)))]).length + ("d")))]);
}
{
    let r = [1, 2, {"d": [1, 3, 42, 3]}];
    r[((3) > 0 ? (3 - 1) : ((r).length + (3)))][(("d") > 0 ? ("d" - 1) : ((r[((3) > 0 ? (3 - 1) : ((r).length + (3)))]).length + ("d")))] = ["a", "b", "c", "d"];
    print(r[((3) > 0 ? (3 - 1) : ((r).length + (3)))][(("d") > 0 ? ("d" - 1) : ((r[((3) > 0 ? (3 - 1) : ((r).length + (3)))]).length + ("d")))][((3) > 0 ? (3 - 1) : ((r[((3) > 0 ? (3 - 1) : ((r).length + (3)))][(("d") > 0 ? ("d" - 1) : ((r[((3) > 0 ? (3 - 1) : ((r).length + (3)))]).length + ("d")))]).length + (3)))]);
}
{
    let r = [1, 2, {"d": [1, 3, 42, 3]}];
    let g = "d";
    r[((3) > 0 ? (3 - 1) : ((r).length + (3)))][((g) > 0 ? (g - 1) : ((r[((3) > 0 ? (3 - 1) : ((r).length + (3)))]).length + (g)))] = ["a", "b", "c", "d"];
    print(r[((3) > 0 ? (3 - 1) : ((r).length + (3)))][(("d") > 0 ? ("d" - 1) : ((r[((3) > 0 ? (3 - 1) : ((r).length + (3)))]).length + ("d")))][((3) > 0 ? (3 - 1) : ((r[((3) > 0 ? (3 - 1) : ((r).length + (3)))][(("d") > 0 ? ("d" - 1) : ((r[((3) > 0 ? (3 - 1) : ((r).length + (3)))]).length + ("d")))]).length + (3)))]);
}
{
    let event = {"event": "$pageview", "properties": {"$browser": "Chrome", "$os": "Windows"}};
    event[(("properties") > 0 ? ("properties" - 1) : ((event).length + ("properties")))][(("$browser") > 0 ? ("$browser" - 1) : ((event[(("properties") > 0 ? ("properties" - 1) : ((event).length + ("properties")))]).length + ("$browser")))] = "Firefox";
    print(event);
}
{
    let event = {"event": "$pageview", "properties": {"$browser": "Chrome", "$os": "Windows"}};
    event.properties["$browser"] = "Firefox";
    print(event);
}
{
    let event = {"event": "$pageview", "properties": {"$browser": "Chrome", "$os": "Windows"}};
    let config = {};
    print(event);
}
