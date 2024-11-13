function print (...args) { console.log(...args.map(__printHogStringOutput)) }
function __printHogStringOutput(obj) { if (typeof obj === 'string') { return obj } return __printHogValue(obj) }
function sha256Hex (str, options) { return 'SHA256 not implemented' }
function md5Hex(string) {
    function cmn(q, a, b, x, s, t) { a = (((a + q) + (x >>> 0) + t) >>> 0); return (((a << s) | (a >>> (32 - s))) + b) >>> 0; }
    function ff(a, b, c, d, x, s, t) { return cmn((b & c) | (~b & d), a, b, x, s, t); }
    function gg(a, b, c, d, x, s, t) { return cmn((b & d) | (c & ~d), a, b, x, s, t); }
    function hh(a, b, c, d, x, s, t) { return cmn(b ^ c ^ d, a, b, x, s, t); }
    function ii(a, b, c, d, x, s, t) { return cmn(c ^ (b | ~d), a, b, x, s, t); }
    function toBytes(str) { var bytes = []; for (var i = 0; i < str.length; i++) bytes.push(str.charCodeAt(i)); return bytes; }
    function toHex(num) {
        var hex = "", i;
        for (i = 0; i < 4; i++)
            hex += ((num >> (i * 8 + 4)) & 0x0F).toString(16) +
                   ((num >> (i * 8)) & 0x0F).toString(16);
        return hex;
    }
    var x = [],
        k, AA, BB, CC, DD, a, b, c, d,
        S = [7, 12, 17, 22, 5, 9, 14, 20, 4, 11, 16, 23, 6, 10, 15, 21],
        T = [
            0xd76aa478, 0xe8c7b756, 0x242070db, 0xc1bdceee,
            0xf57c0faf, 0x4787c62a, 0xa8304613, 0xfd469501,
            0x698098d8, 0x8b44f7af, 0xffff5bb1, 0x895cd7be,
            0x6b901122, 0xfd987193, 0xa679438e, 0x49b40821,
            0xf61e2562, 0xc040b340, 0x265e5a51, 0xe9b6c7aa,
            0xd62f105d,  0x2441453, 0xd8a1e681, 0xe7d3fbc8,
            0x21e1cde6, 0xc33707d6, 0xf4d50d87, 0x455a14ed,
            0xa9e3e905, 0xfcefa3f8, 0x676f02d9, 0x8d2a4c8a,
            0xfffa3942, 0x8771f681, 0x6d9d6122, 0xfde5380c,
            0xa4beea44, 0x4bdecfa9, 0xf6bb4b60, 0xbebfbc70,
            0x289b7ec6, 0xeaa127fa, 0xd4ef3085,  0x4881d05,
            0xd9d4d039, 0xe6db99e5, 0x1fa27cf8, 0xc4ac5665,
            0xf4292244, 0x432aff97, 0xab9423a7, 0xfc93a039,
            0x655b59c3, 0x8f0ccc92, 0xffeff47d, 0x85845dd1,
            0x6fa87e4f, 0xfe2ce6e0, 0xa3014314, 0x4e0811a1,
            0xf7537e82, 0xbd3af235, 0x2ad7d2bb, 0xeb86d391
        ];
    var data = toBytes(string);
    var originalLength = data.length * 8;
    data.push(0x80);
    while ((data.length % 64) != 56)
        data.push(0);
    for (var i = 0; i < 8; i++)
        data.push((originalLength >>> (i * 8)) & 0xFF);
    for (i = 0; i < data.length; i += 64) {
        x = [];
        for (var j = 0; j < 64; j += 4) {
            x.push(
                data[i + j] |
                (data[i + j + 1] << 8) |
                (data[i + j + 2] << 16) |
                (data[i + j + 3] << 24)
            );
        }
        a = 0x67452301;
        b = 0xEFCDAB89;
        c = 0x98BADCFE;
        d = 0x10325476;
        for (j = 0; j < 64; j++) {
            if (j < 16) {
                k = j;
                AA = ff(a, b, c, d, x[k], S[j % 4], T[j]);
            } else if (j < 32) {
                k = (5 * j + 1) % 16;
                AA = gg(a, b, c, d, x[k], S[(j % 4) + 4], T[j]);
            } else if (j < 48) {
                k = (3 * j + 5) % 16;
                AA = hh(a, b, c, d, x[k], S[(j % 4) + 8], T[j]);
            } else {
                k = (7 * j) % 16;
                AA = ii(a, b, c, d, x[k], S[(j % 4) + 12], T[j]);
            }
            a = d;
            d = c;
            c = b;
            b = AA;
        }
        a = (a + 0x67452301) >>> 0;
        b = (b + 0xEFCDAB89) >>> 0;
        c = (c + 0x98BADCFE) >>> 0;
        d = (d + 0x10325476) >>> 0;
    }
    return toHex(a) + toHex(b) + toHex(c) + toHex(d);
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
function __isHogCallable(obj) { return obj && typeof obj === 'function' && obj.__isHogCallable__ }
function __isHogClosure(obj) { return obj && obj.__isHogClosure__ === true }
function __isHogError(obj) {return obj && obj.__hogError__ === true}
function __isHogDate(obj) { return obj && obj.__hogDate__ === true }
function __isHogDateTime(obj) { return obj && obj.__hogDateTime__ === true }
function sha256HmacChainHex (data, options) { return 'sha256HmacChainHex not implemented' }

let string = "this is a secure string";
print("string:", string);
print("md5Hex(string):", md5Hex(string));
print("sha256Hex(string):", sha256Hex(string));
let data = ["1", "string", "more", "keys"];
print("data:", data);
print("sha256HmacChainHex(data):", sha256HmacChainHex(data));
