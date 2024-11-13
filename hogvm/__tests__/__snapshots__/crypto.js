
const escapeCharsMap = { '\b': '\\b', '\f': '\\f', '\r': '\\r', '\n': '\\n', '\t': '\\t', '\0': '\\0', '\v': '\\v', '\\': '\\\\' };
const singlequoteEscapeCharsMap = { ...escapeCharsMap, "'": "\\'" };
const backquoteEscapeCharsMap = { ...escapeCharsMap, '`': '\\`' };
function escapeString(value) { return `'${value.split('').map((c) => singlequoteEscapeCharsMap[c] || c).join('')}'`; }
function escapeIdentifier(identifier) {
    if (typeof identifier === 'number') return identifier.toString();
    if (/^[A-Za-z_$][A-Za-z0-9_$]*$/.test(identifier)) return identifier;
    return `\`${identifier.split('').map((c) => backquoteEscapeCharsMap[c] || c).join('')}\``;
}
function isHogCallable(obj) { return obj && typeof obj === 'object' && '__hogCallable__' in obj && 'argCount' in obj && 'ip' in obj && 'upvalueCount' in obj; }
function isHogClosure(obj) { return obj && typeof obj === 'object' && '__hogClosure__' in obj && 'callable' in obj && 'upvalues' in obj; }
function isHogDate(obj) { return obj && typeof obj === 'object' && '__hogDate__' in obj && 'year' in obj && 'month' in obj && 'day' in obj; }
function isHogDateTime(obj) { return obj && typeof obj === 'object' && '__hogDateTime__' in obj && 'dt' in obj && 'zone' in obj; }
function isHogError(obj) { return obj && typeof obj === 'object' && '__hogError__' in obj && 'type' in obj && 'message' in obj; }
function printHogValue(obj, marked = new Set()) {
    if (typeof obj === 'object' && obj !== null && obj !== undefined) {
        if (marked.has(obj) && !isHogDateTime(obj) && !isHogDate(obj) && !isHogError(obj) && !isHogClosure(obj) && !isHogCallable(obj)) {
            return 'null';
        }
        marked.add(obj);
        try {
            if (Array.isArray(obj)) {
                if (obj.__isHogTuple) {
                    return obj.length < 2 ? `tuple(${obj.map((o) => printHogValue(o, marked)).join(', ')})` : `(${obj.map((o) => printHogValue(o, marked)).join(', ')})`;
                }
                return `[${obj.map((o) => printHogValue(o, marked)).join(', ')}]`;
            }
            if (isHogDateTime(obj)) {
                const millis = String(obj.dt);
                return `DateTime(${millis}${millis.includes('.') ? '' : '.0'}, ${escapeString(obj.zone)})`;
            }
            if (isHogDate(obj)) return `Date(${obj.year}, ${obj.month}, ${obj.day})`;
            if (isHogError(obj)) {
                return `${String(obj.type)}(${escapeString(obj.message)}${obj.payload ? `, ${printHogValue(obj.payload, marked)}` : ''})`;
            }
            if (isHogClosure(obj)) return printHogValue(obj.callable, marked);
            if (isHogCallable(obj)) return `fn<${escapeIdentifier(obj.name ?? 'lambda')}(${printHogValue(obj.argCount)})>`;
            if (obj instanceof Map) {
                return `{${Array.from(obj.entries()).map(([key, value]) => `${printHogValue(key, marked)}: ${printHogValue(value, marked)}`).join(', ')}}`;
            }
            return `{${Object.entries(obj).map(([key, value]) => `${printHogValue(key, marked)}: ${printHogValue(value, marked)}`).join(', ')}}`;
        } finally {
            marked.delete(obj);
        }
    } else if (typeof obj === 'boolean') return obj ? 'true' : 'false';
    else if (obj === null || obj === undefined) return 'null';
    else if (typeof obj === 'string') return escapeString(obj);
    return obj.toString();
}
function printHogStringOutput(obj) { return typeof obj === 'string' ? obj : printHogValue(obj); }
let string = "this is a secure string";
console.log(printHogStringOutput("string:"), printHogStringOutput(string));
console.log(printHogStringOutput("md5Hex(string):"), printHogStringOutput(md5(string)));
console.log(printHogStringOutput("sha256Hex(string):"), printHogStringOutput(sha256(string)));
let data = ["1", "string", "more", "keys"];
console.log(printHogStringOutput("data:"), printHogStringOutput(data));
console.log(printHogStringOutput("sha256HmacChainHex(data):"), printHogStringOutput(sha256HmacChainHex([data])));
