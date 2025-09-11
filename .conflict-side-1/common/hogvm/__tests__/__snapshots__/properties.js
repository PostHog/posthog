function tuple (...args) { const tuple = args.slice(); tuple.__isHogTuple = true; return tuple; }
function print (...args) { console.log(...args.map(__printHogStringOutput)) }
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

{
    let r = [1, 2, {"d": tuple(1, 3, 42, 6)}];
    print(__getProperty(__getProperty(__getProperty(r, 3, false), "d", false), 2, false));
}
{
    let r = [1, 2, {"d": tuple(1, 3, 42, 6)}];
    print(__getProperty(__getProperty(__getProperty(r, 3, false), "d", false), 3, false));
}
{
    let r = [1, 2, {"d": tuple(1, 3, 42, 6)}];
    print(__getProperty(__getProperty(__getProperty(r, 3, false), "d", false), 4, false));
}
{
    let r = {"d": tuple(1, 3, 42, 6)};
    print(__getProperty(__getProperty(r, "d", true), 2, false));
}
{
    let r = [1, 2, {"d": [1, 3, 42, 3]}];
    __setProperty(__getProperty(__getProperty(r, 3, false), "d", false), 3, 3);
    print(__getProperty(__getProperty(__getProperty(r, 3, false), "d", false), 3, false));
}
{
    let r = [1, 2, {"d": [1, 3, 42, 3]}];
    __setProperty(__getProperty(__getProperty(r, 3, false), "d", false), 3, 3);
    print(__getProperty(__getProperty(__getProperty(r, 3, false), "d", false), 3, false));
}
{
    let r = [1, 2, {"d": [1, 3, 42, 3]}];
    __setProperty(__getProperty(r, 3, false), "c", [666]);
    print(__getProperty(r, 3, false));
}
{
    let r = [1, 2, {"d": [1, 3, 42, 3]}];
    __setProperty(__getProperty(__getProperty(r, 3, false), "d", false), 3, 3);
    print(__getProperty(__getProperty(r, 3, false), "d", false));
}
{
    let r = [1, 2, {"d": [1, 3, 42, 3]}];
    __setProperty(__getProperty(r, 3, false), "d", ["a", "b", "c", "d"]);
    print(__getProperty(__getProperty(__getProperty(r, 3, false), "d", false), 3, false));
}
{
    let r = [1, 2, {"d": [1, 3, 42, 3]}];
    let g = "d";
    __setProperty(__getProperty(r, 3, false), g, ["a", "b", "c", "d"]);
    print(__getProperty(__getProperty(__getProperty(r, 3, false), "d", false), 3, false));
}
{
    let event = {"event": "$pageview", "properties": {"$browser": "Chrome", "$os": "Windows"}};
    __setProperty(__getProperty(event, "properties", false), "$browser", "Firefox");
    print(event);
}
{
    let event = {"event": "$pageview", "properties": {"$browser": "Chrome", "$os": "Windows"}};
    __setProperty(__getProperty(event, "properties", true), "$browser", "Firefox")
    print(event);
}
{
    let event = {"event": "$pageview", "properties": {"$browser": "Chrome", "$os": "Windows"}};
    let config = {};
    print(event);
}
