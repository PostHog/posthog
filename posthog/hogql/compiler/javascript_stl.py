STL_FUNCTIONS: dict[str, list[str | list[str]]] = {
    "concat": [
        "function concat (...args) { return args.map((arg) => (arg === null ? '' : __STLToString([arg]))).join('') }",
        ["__STLToString"],
    ],
    "match": [
        "function match (str, pattern) { return new RegExp(pattern).test(str) }",
        [],
    ],
    "like": [
        "function like (str, pattern) { return __like(str, pattern, false) }",
        ["__like"],
    ],
    "ilike": [
        "function ilike (str, pattern) { return __like(str, pattern, true) }",
        ["__like"],
    ],
    "notLike": [
        "function notLike (str, pattern) { return !__like(str, pattern, false) }",
        ["__like"],
    ],
    "notILike": [
        "function notILike (str, pattern) { return !__like(str, pattern, true) }",
        ["__like"],
    ],
    "toString": [
        "function toString (value) { return __STLToString([value]) }",
        ["__STLToString"],
    ],
    "toUUID": [
        "function toUUID (value) { return __STLToString([value]) }",
        ["__STLToString"],
    ],
    "toInt": [
        """function toInt (value) {
    if (__isHogDateTime(value)) {
        return Math.floor(value.dt)
    } else if (__isHogDate(value)) {
        const day = DateTime.fromObject({ year: value.year, month: value.month, day: value.day })
        const epoch = DateTime.fromObject({ year: 1970, month: 1, day: 1 })
        return Math.floor(day.diff(epoch, 'days').days)
    }
    return !isNaN(parseInt(value)) ? parseInt(value) : null
}""",
        ["__isHogDateTime", "__isHogDate"],
    ],
    "toFloat": [
        """function toFloat (value) {
    if (__isHogDateTime(value)) {
        return value.dt
    } else if (__isHogDate(value)) {
        const day = DateTime.fromObject({ year: value.year, month: value.month, day: value.day })
        const epoch = DateTime.fromObject({ year: 1970, month: 1, day: 1 })
        return Math.floor(day.diff(epoch, 'days').days)
    }
    return !isNaN(parseFloat(value)) ? parseFloat(value) : null}""",
        ["__isHogDateTime", "__isHogDate"],
    ],
    "ifNull": [
        "function ifNull (value, defaultValue) { return value !== null ? value : defaultValue } ",
        [],
    ],
    "length": [
        "function length (value) { return value.length }",
        [],
    ],
    "empty": [
        """function empty (value) {
    if (typeof value === 'object') {
        if (Array.isArray(value)) {
            return value.length === 0
        } else if (value === null) {
            return true
        } else if (value instanceof Map) {
            return value.size === 0
        }
        return Object.keys(value).length === 0
    } else if (typeof value === 'number' || typeof value === 'boolean') {
        return false
    }
    return !value
}""",
        [],
    ],
    "notEmpty": [
        "function notEmpty (value) { return !empty(value) }",
        ["empty"],
    ],
    "tuple": [
        "function tuple (...args) { const tuple = args.slice(); tuple.__isHogTuple = true; return tuple; }",
        [],
    ],
    "lower": [
        "function lower (value) { return value.toLowerCase() }",
        [],
    ],
    "upper": [
        "function upper (value) { return value.toUpperCase() }",
        [],
    ],
    "reverse": [
        "function reverse (value) { return value.split('').reverse().join('') }",
        [],
    ],
    "print": [
        "function print (...args) { console.log(...args.map(__printHogStringOutput)) }",
        ["__printHogStringOutput"],
    ],
    "jsonParse": [
        """function jsonParse (str) {
    function convert(x) {
        if (Array.isArray(x)) {
            return x.map(convert)
        } else if (typeof x === 'object' && x !== null) {
            if (x.__hogDateTime__) {
                return __toHogDateTime(x.dt, x.zone)
            } else if (x.__hogDate__) {
                return __toHogDate(x.year, x.month, x.day)
            } else if (x.__hogError__) {
                return __newHogError(x.type, x.message, x.payload)
            }
            const map = new Map()
            for (const key in x) {
                map.set(key, convert(x[key]))
            }
            return map
        }
        return x
    }
    return convert(JSON.parse(str))
}""",
        ["__toHogDateTime", "__toHogDate", "__newHogError"],
    ],
    "jsonStringify": [
        """function jsonStringify (value, spacing) {
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
}""",
        ["__isHogDateTime", "__isHogDate", "__isHogError", "__isHogCallable", "__isHogClosure"],
    ],
    "JSONHas": [
        """function JSONHas (obj, ...path) {
    let current = obj
    for (const key of path) {
        let currentParsed = current
        if (typeof current === 'string') {
            try {
                currentParsed = JSON.parse(current)
            } catch (e) {
                return false
            }
        }
        if (currentParsed instanceof Map) {
            if (!currentParsed.has(key)) {
                return false
            }
            current = currentParsed.get(key)
        } else if (typeof currentParsed === 'object' && currentParsed !== null) {
            if (typeof key === 'number') {
                if (Array.isArray(currentParsed)) {
                    if (key < 0) {
                        if (key < -currentParsed.length) {
                            return false
                        }
                        current = currentParsed[currentParsed.length + key]
                    } else if (key === 0) {
                        return false
                    } else {
                        if (key > currentParsed.length) {
                            return false
                        }
                        current = currentParsed[key - 1]
                    }
                } else {
                    return false
                }
            } else {
                if (!(key in currentParsed)) {
                    return false
                }
                current = currentParsed[key]
            }
        } else {
            return false
        }
    }
    return true
}""",
        [],
    ],
    "isValidJSON": [
        "function isValidJSON (str) { try { JSON.parse(str); return true } catch (e) { return false } }",
        [],
    ],
    "JSONLength": [
        """function JSONLength (obj, ...path) {
    try {
        if (typeof obj === 'string') {
            obj = JSON.parse(obj)
        }
    } catch (e) {
        return 0
    }
    if (typeof obj === 'object' && obj !== null) {
        const value = __getNestedValue(obj, path, true)
        if (Array.isArray(value)) {
            return value.length
        } else if (value instanceof Map) {
            return value.size
        } else if (typeof value === 'object' && value !== null) {
            return Object.keys(value).length
        }
    }
    return 0
}""",
        ["__getNestedValue"],
    ],
    "JSONExtractBool": [
        """function JSONExtractBool (obj, ...path) {
    try {
        if (typeof obj === 'string') {
            obj = JSON.parse(obj)
        }
    } catch (e) {
        return false
    }
    if (path.length > 0) {
        obj = __getNestedValue(obj, path, true)
    }
    if (typeof obj === 'boolean') {
        return obj
    }
    return false
}""",
        ["__getNestedValue"],
    ],
    "base64Encode": [
        "function base64Encode (str) { return Buffer.from(str).toString('base64') }",
        [],
    ],
    "base64Decode": [
        "function base64Decode (str) { return Buffer.from(str, 'base64').toString() } ",
        [],
    ],
    "tryBase64Decode": [
        "function tryBase64Decode (str) { try { return Buffer.from(str, 'base64').toString() } catch (e) { return '' } }",
        [],
    ],
    "encodeURLComponent": [
        "function encodeURLComponent (str) { return encodeURIComponent(str) }",
        [],
    ],
    "decodeURLComponent": [
        "function decodeURLComponent (str) { return decodeURIComponent(str) }",
        [],
    ],
    "replaceOne": [
        "function replaceOne (str, searchValue, replaceValue) { return str.replace(searchValue, replaceValue) }",
        [],
    ],
    "replaceAll": [
        "function replaceAll (str, searchValue, replaceValue) { return str.replaceAll(searchValue, replaceValue) }",
        [],
    ],
    "position": [
        "function position (str, elem) { if (typeof str === 'string') { return str.indexOf(String(elem)) + 1 } else { return 0 } }",
        [],
    ],
    "positionCaseInsensitive": [
        "function positionCaseInsensitive (str, elem) { if (typeof str === 'string') { return str.toLowerCase().indexOf(String(elem).toLowerCase()) + 1 } else { return 0 } }",
        [],
    ],
    "trim": [
        """function trim (str, char) {
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
}""",
        [],
    ],
    "trimLeft": [
        """function trimLeft (str, char) {
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
}""",
        [],
    ],
    "trimRight": [
        """function trimRight (str, char) {
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
}""",
        [],
    ],
    "splitByString": [
        "function splitByString (separator, str, maxSplits) { if (maxSplits === undefined || maxSplits === null) { return str.split(separator) } return str.split(separator, maxSplits) }",
        [],
    ],
    "generateUUIDv4": [
        "function generateUUIDv4 () { return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function (c) { const r = (Math.random() * 16) | 0; const v = c === 'x' ? r : (r & 0x3) | 0x8; return v.toString(16) })}",
        [],
    ],
    "sha256Hex": [
        "function sha256Hex (str, options) { return 'SHA256 not implemented' }",
        [],
    ],
    "md5Hex": [
        """function md5Hex(string) {
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
}""",
        [],
    ],
    "sha256HmacChainHex": [
        "function sha256HmacChainHex (data, options) { return 'sha256HmacChainHex not implemented' }",
        [],
    ],
    "keys": [
        """function keys (obj) {
    if (typeof obj === 'object' && obj !== null) {
        if (Array.isArray(obj)) {
            return Array.from(obj.keys())
        } else if (obj instanceof Map) {
            return Array.from(obj.keys())
        }
        return Object.keys(obj)
    }
    return []
}""",
        [],
    ],
    "values": [
        """function values (obj) {
    if (typeof obj === 'object' && obj !== null) {
        if (Array.isArray(obj)) {
            return [...obj]
        } else if (obj instanceof Map) {
            return Array.from(obj.values())
        }
        return Object.values(obj)
    }
    return []
}""",
        [],
    ],
    "indexOf": [
        "function indexOf (arrOrString, elem) { if (Array.isArray(arrOrString)) { return arrOrString.indexOf(elem) + 1 } else { return 0 } }",
        [],
    ],
    "arrayPushBack": [
        "function arrayPushBack (arr, item) { if (!Array.isArray(arr)) { return [item] } return [...arr, item] }",
        [],
    ],
    "arrayPushFront": [
        "function arrayPushFront (arr, item) { if (!Array.isArray(arr)) { return [item] } return [item, ...arr] }",
        [],
    ],
    "arrayPopBack": [
        "function arrayPopBack (arr) { if (!Array.isArray(arr)) { return [] } return arr.slice(0, arr.length - 1) }",
        [],
    ],
    "arrayPopFront": [
        "function arrayPopFront (arr) { if (!Array.isArray(arr)) { return [] } return arr.slice(1) }",
        [],
    ],
    "arraySort": [
        "function arraySort (arr) { if (!Array.isArray(arr)) { return [] } return [...arr].sort() }",
        [],
    ],
    "arrayReverse": [
        "function arrayReverse (arr) { if (!Array.isArray(arr)) { return [] } return [...arr].reverse() }",
        [],
    ],
    "arrayReverseSort": [
        "function arrayReverseSort (arr) { if (!Array.isArray(arr)) { return [] } return [...arr].sort().reverse() }",
        [],
    ],
    "arrayStringConcat": [
        "function arrayStringConcat (arr, separator = '') { if (!Array.isArray(arr)) { return '' } return arr.join(separator) }",
        [],
    ],
    "arrayCount": [
        "function arrayCount (func, arr) { let count = 0; for (let i = 0; i < arr.length; i++) { if (func(arr[i])) { count = count + 1 } } return count }",
        [],
    ],
    "arrayExists": [
        """function arrayExists (func, arr) { for (let i = 0; i < arr.length; i++) { if (func(arr[i])) { return true } } return false }""",
        [],
    ],
    "arrayFilter": [
        """function arrayFilter (func, arr) { let result = []; for (let i = 0; i < arr.length; i++) { if (func(arr[i])) { result = arrayPushBack(result, arr[i]) } } return result}""",
        ["arrayPushBack"],
    ],
    "arrayMap": [
        """function arrayMap (func, arr) { let result = []; for (let i = 0; i < arr.length; i++) { result = arrayPushBack(result, func(arr[i])) } return result }""",
        ["arrayPushBack"],
    ],
    "has": [
        """function has (arr, elem) { if (!Array.isArray(arr) || arr.length === 0) { return false } return arr.includes(elem) }""",
        [],
    ],
    "now": [
        """function now () { return __now() }""",
        ["__now"],
    ],
    "toUnixTimestamp": [
        """function toUnixTimestamp (input, zone) { return __toUnixTimestamp(input, zone) }""",
        ["__toUnixTimestamp"],
    ],
    "fromUnixTimestamp": [
        """function fromUnixTimestamp (input) { return __fromUnixTimestamp(input) }""",
        ["__fromUnixTimestamp"],
    ],
    "toUnixTimestampMilli": [
        """function toUnixTimestampMilli (input, zone) { return __toUnixTimestampMilli(input, zone) }""",
        ["__toUnixTimestampMilli"],
    ],
    "fromUnixTimestampMilli": [
        """function fromUnixTimestampMilli (input) { return __fromUnixTimestampMilli(input) }""",
        ["__fromUnixTimestampMilli"],
    ],
    "toTimeZone": [
        """function toTimeZone (input, zone) { return __toTimeZone(input, zone) }""",
        ["__toTimeZone"],
    ],
    "toDate": [
        """function toDate (input) { return __toDate(input) }""",
        ["__toDate"],
    ],
    "toDateTime": [
        """function toDateTime (input, zone) { return __toDateTime(input, zone) }""",
        ["__toDateTime"],
    ],
    "formatDateTime": [
        """function formatDateTime (input, format, zone) { return __formatDateTime(input, format, zone) }""",
        ["__formatDateTime"],
    ],
    "HogError": [
        """function HogError (type, message, payload) { return __newHogError(type, message, payload) }""",
        ["__newHogError"],
    ],
    "Error": [
        """function __x_Error (message, payload) { return __newHogError('Error', message, payload) }""",
        ["__newHogError"],
    ],
    "RetryError": [
        """function RetryError (message, payload) { return __newHogError('RetryError', message, payload) }""",
        ["__newHogError"],
    ],
    "NotImplementedError": [
        """function NotImplementedError (message, payload) { return __newHogError('NotImplementedError', message, payload) }""",
        ["__newHogError"],
    ],
    "typeof": [
        """
function __x_typeof (value) {
    if (value === null || value === undefined) {
        return 'null'
    } else if (__isHogDateTime(value)) {
        return 'datetime'
    } else if (__isHogDate(value)) {
        return 'date'
    } else if (__isHogError(value)) {
        return 'error'
    } else if (__isHogCallable(value) || __isHogClosure(value)) {
        return 'function'
    } else if (Array.isArray(value)) {
        if (value.__isHogTuple) {
            return 'tuple'
        }
        return 'array'
    } else if (typeof value === 'object') {
        return 'object'
    } else if (typeof value === 'number') {
        return Number.isInteger(value) ? 'integer' : 'float'
    } else if (typeof value === 'string') {
        return 'string'
    } else if (typeof value === 'boolean') {
        return 'boolean'
    }
    return 'unknown'
}
""",
        ["__isHogDateTime", "__isHogDate", "__isHogError", "__isHogCallable", "__isHogClosure"],
    ],
    "__STLToString": [
        r"""
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
""",
        ["__isHogDate", "__isHogDateTime", "__printHogStringOutput"],
    ],
    "__isHogDate": [
        """function __isHogDate(obj) { return obj && obj.__hogDate__ === true }""",
        [],
    ],
    "__isHogDateTime": [
        """function __isHogDateTime(obj) { return obj && obj.__hogDateTime__ === true }""",
        [],
    ],
    "__toHogDate": [
        """function __toHogDate(year, month, day) { return { __hogDate__: true, year: year, month: month, day: day, } }""",
        [],
    ],
    "__toHogDateTime": [
        """
function __toHogDateTime(timestamp, zone) {
    if (__isHogDate(timestamp)) {
        const dateTime = DateTime.fromObject(
            {
                year: timestamp.year,
                month: timestamp.month,
                day: timestamp.day,
            },
            { zone: zone || 'UTC' }
        )
        return {
            __hogDateTime__: true,
            dt: dateTime.toSeconds(),
            zone: dateTime.zoneName || 'UTC',
        }
    }
    return {
        __hogDateTime__: true,
        dt: timestamp,
        zone: zone || 'UTC',
    }
}
""",
        ["__isHogDate"],
    ],
    "__now": [
        """function __now(zone) { return __toHogDateTime(Date.now() / 1000, zone) }""",
        ["__toHogDateTime"],
    ],
    "__toUnixTimestamp": [
        """
function __toUnixTimestamp(input, zone) {
    if (__isHogDateTime(input)) {
        return input.dt
    }
    if (__isHogDate(input)) {
        return __toHogDateTime(input).dt
    }
    return DateTime.fromISO(input, { zone: zone || 'UTC' }).toSeconds()
}
""",
        ["__isHogDateTime", "__isHogDate", "__toHogDateTime"],
    ],
    "__fromUnixTimestamp": [
        """function __fromUnixTimestamp(input) { return __toHogDateTime(input) }""",
        ["__toHogDateTime"],
    ],
    "__toUnixTimestampMilli": [
        """function __toUnixTimestampMilli(input, zone) { return __toUnixTimestamp(input, zone) * 1000 }""",
        ["__toUnixTimestamp"],
    ],
    "__fromUnixTimestampMilli": [
        """function __fromUnixTimestampMilli(input) { return __toHogDateTime(input / 1000) }""",
        ["__toHogDateTime"],
    ],
    "__toTimeZone": [
        """function __toTimeZone(input, zone) { if (!__isHogDateTime(input)) { throw new Error('Expected a DateTime') }; return { ...input, zone }}""",
        ["__isHogDateTime"],
    ],
    "__toDate": [
        """function __toDate(input) { const dt = typeof input === 'number' ? DateTime.fromSeconds(input) : DateTime.fromISO(input); return { __hogDate__: true, year: dt.year, month: dt.month, day: dt.day, } }""",
        [],
    ],
    "__toDateTime": [
        """
function __toDateTime(input, zone) {
    const dt = typeof input === 'number' ? input : DateTime.fromISO(input, { zone: zone || 'UTC' }).toSeconds()
    return {
        __hogDateTime__: true,
        dt: dt,
        zone: zone || 'UTC',
    }
}
""",
        [],
    ],
    "__formatDateTime": [
        """
function __formatDateTime(input, format, zone) {
    if (!__isHogDateTime(input)) {
        throw new Error('Expected a DateTime')
    }
    if (!format) {
        throw new Error('formatDateTime requires at least 2 arguments')
    }
    let formatString = ''
    let acc = ''
    const tokenTranslations = {
        a: 'EEE',
        b: 'MMM',
        c: 'MM',
        C: 'yy',
        d: 'dd',
        D: 'MM/dd/yy',
        e: 'd',
        f: 'SSS',
        F: 'yyyy-MM-dd',
        g: 'yy',
        G: 'yyyy',
        h: 'hh',
        H: 'HH',
        i: 'mm',
        I: 'hh',
        j: 'ooo',
        k: 'HH',
        l: 'hh',
        m: 'MM',
        M: 'MMMM',
        n: '\\n',
        p: 'a',
        Q: 'q',
        r: 'hh:mm a',
        R: 'HH:mm',
        s: 'ss',
        S: 'ss',
        t: '\\t',
        T: 'HH:mm:ss',
        u: 'E',
        V: 'WW',
        w: 'E',
        W: 'EEEE',
        y: 'yy',
        Y: 'yyyy',
        z: 'ZZZ',
        '%': '%',
    }
    for (let i = 0; i < format.length; i++) {
        if (format[i] === '%') {
            if (acc.length > 0) {
                formatString += `'\\${acc}'`
                acc = ''
            }
            i += 1
            if (i < format.length && tokenTranslations[format[i]]) {
                formatString += tokenTranslations[format[i]]
            }
        } else {
            acc += format[i]
        }
    }
    if (acc.length > 0) {
        formatString += `'\\${acc}'`
    }
    return DateTime.fromSeconds(input.dt, { zone: zone || input.zone }).toFormat(formatString)
}
""",
        ["__isHogDateTime"],
    ],
    "__printHogStringOutput": [
        """function __printHogStringOutput(obj) { if (typeof obj === 'string') { return obj } return __printHogValue(obj) } """,
        ["__printHogValue"],
    ],
    "__printHogValue": [
        """
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
""",
        [
            "__isHogDateTime",
            "__isHogDate",
            "__isHogError",
            "__isHogClosure",
            "__isHogCallable",
            "__escapeString",
            "__escapeIdentifier",
        ],
    ],
    "__escapeString": [
        """
function __escapeString(value) {
    const singlequoteEscapeCharsMap = { '\\b': '\\\\b', '\\f': '\\\\f', '\\r': '\\\\r', '\\n': '\\\\n', '\\t': '\\\\t', '\\0': '\\\\0', '\\v': '\\\\v', '\\\\': '\\\\\\\\', "'": "\\\\'" }
    return `'${value.split('').map((c) => singlequoteEscapeCharsMap[c] || c).join('')}'`;
}
""",
        [],
    ],
    "__escapeIdentifier": [
        """
function __escapeIdentifier(identifier) {
    const backquoteEscapeCharsMap = { '\\b': '\\\\b', '\\f': '\\\\f', '\\r': '\\\\r', '\\n': '\\\\n', '\\t': '\\\\t', '\\0': '\\\\0', '\\v': '\\\\v', '\\\\': '\\\\\\\\', '`': '\\\\`' }
    if (typeof identifier === 'number') return identifier.toString();
    if (/^[A-Za-z_$][A-Za-z0-9_$]*$/.test(identifier)) return identifier;
    return `\\`${identifier.split('').map((c) => backquoteEscapeCharsMap[c] || c).join('')}\\``;
}
""",
        [],
    ],
    "__newHogError": [
        """
function __newHogError(type, message, payload) {
    let error = new Error(message || 'An error occurred');
    error.__hogError__ = true
    error.type = type
    error.payload = payload
    return error
}
""",
        [],
    ],
    "__isHogError": [
        """function __isHogError(obj) {return obj && obj.__hogError__ === true}""",
        [],
    ],
    "__isHogCallable": [
        """function __isHogCallable(obj) { return obj && typeof obj === 'function' && obj.__isHogCallable__ }""",
        [],
    ],
    "__isHogClosure": [
        """function __isHogClosure(obj) { return obj && obj.__isHogClosure__ === true }""",
        [],
    ],
    "__getNestedValue": [
        """
function __getNestedValue(obj, path, allowNull = false) {
    let current = obj
    for (const key of path) {
        if (current == null) {
            return null
        }
        if (current instanceof Map) {
            current = current.get(key)
        } else if (typeof current === 'object' && current !== null) {
            current = current[key]
        } else {
            return null
        }
    }
    if (current === null && !allowNull) {
        return null
    }
    return current
}
""",
        [],
    ],
    "__like": [
        """
function __like(str, pattern, caseInsensitive = false) {
    if (caseInsensitive) {
        str = str.toLowerCase()
        pattern = pattern.toLowerCase()
    }
    pattern = String(pattern)
        .replaceAll(/[-/\\\\^$*+?.()|[\\]{}]/g, '\\\\$&')
        .replaceAll('%', '.*')
        .replaceAll('_', '.')
    return new RegExp(pattern).test(str)
}
""",
        [],
    ],
    "__getProperty": [
        """
function __getProperty(objectOrArray, key, nullish) {
    if ((nullish && !objectOrArray) || key === 0) { return null }
    if (Array.isArray(objectOrArray)) {
        return key > 0 ? objectOrArray[key - 1] : objectOrArray[objectOrArray.length + key]
    } else {
        return objectOrArray[key]
    }
}
""",
        [],
    ],
    "__setProperty": [
        """
function __setProperty(objectOrArray, key, value) {
    if (Array.isArray(objectOrArray)) {
        if (key > 0) {
            objectOrArray[key - 1] = value
        } else {
            objectOrArray[objectOrArray.length + key] = value
        }
    } else {
        objectOrArray[key] = value
    }
    return objectOrArray
}
""",
        [],
    ],
    "__lambda": [
        """function __lambda (fn) { return fn }""",
        [],
    ],
}


def import_stl_functions(requested_functions):
    """
    Given a list of requested function names, returns a string containing the code
    for these functions and all their dependencies, in an order suitable for evaluation.
    """

    # Set to keep track of all required functions
    required_functions = set()
    visited = set()

    # Recursive function to find all dependencies
    def dfs(func_name):
        if func_name in visited:
            return
        visited.add(func_name)
        if func_name not in STL_FUNCTIONS:
            raise ValueError(f"Function '{func_name}' is not defined.")
        _, dependencies = STL_FUNCTIONS[func_name]
        for dep in dependencies:
            dfs(dep)
        required_functions.add(func_name)

    # Start DFS from each requested function
    for func in requested_functions:
        dfs(func)

    # Build the dependency graph
    dependency_graph = {}
    for func in required_functions:
        _, dependencies = STL_FUNCTIONS[func]
        dependency_graph[func] = dependencies

    # Perform topological sort
    def topological_sort(graph):
        visited = set()
        temp_mark = set()
        result = []

        def visit(node):
            if node in visited:
                return
            if node in temp_mark:
                raise ValueError("Circular dependency detected")
            temp_mark.add(node)
            for neighbor in graph.get(node, []):
                visit(neighbor)
            temp_mark.remove(node)
            visited.add(node)
            result.append(node)

        for node in graph:
            visit(node)
        return result[::-1]  # reverse the list to get correct order

    sorted_functions = topological_sort(dependency_graph)

    # Build the final code
    code_pieces = []
    for func in sorted_functions:
        code, _ = STL_FUNCTIONS[func]
        code_pieces.append(str(code).strip())

    return "\n".join(code_pieces)
