function upper (value) { return value.toUpperCase() }
function __x_typeof (value) {
    if (value === null || value === undefined) { return 'null'
    } else if (__isHogDateTime(value)) { return 'datetime'
    } else if (__isHogDate(value)) { return 'date'
    } else if (__isHogError(value)) { return 'error'
    } else if (typeof value === 'function') { return 'function'
    } else if (Array.isArray(value)) { if (value.__isHogTuple) { return 'tuple' } return 'array'
    } else if (typeof value === 'object') { return 'object'
    } else if (typeof value === 'number') { return Number.isInteger(value) ? 'integer' : 'float'
    } else if (typeof value === 'string') { return 'string'
    } else if (typeof value === 'boolean') { return 'boolean' }
    return 'unknown'
}
function tuple (...args) { const tuple = args.slice(); tuple.__isHogTuple = true; return tuple; }
function today() {
    const now = new Date();
    return __toHogDate(now.getUTCFullYear(), now.getUTCMonth()+1, now.getUTCDate());
}
function toYear(value) { return extract('year', value) }
function toYYYYMM(value) {
    const y = extract('year', value);
    const m = extract('month', value);
    return y*100 + m;
}
function toStartOfWeek(value) {
    if (!__isHogDateTime(value) && !__isHogDate(value)) {
        throw new Error('Expected HogDate or HogDateTime');
    }
    let d;
    if (__isHogDate(value)) {
        d = new Date(Date.UTC(value.year, value.month - 1, value.day));
    } else {
        d = new Date(value.dt * 1000);
    }
    // Monday=1,... Sunday=7
    // getUTCDay(): Sunday=0,... Saturday=6
    // We want ISO weekday: Monday=1,... Sunday=7
    let dayOfWeek = d.getUTCDay(); // Sunday=0,...
    let isoWeekday = dayOfWeek === 0 ? 7 : dayOfWeek;

    // subtract isoWeekday-1 days
    const start = new Date(d.getTime() - (isoWeekday - 1) * 24 * 3600 * 1000);

    // Zero out hours, minutes, seconds, ms
    start.setUTCHours(0, 0, 0, 0);

    return { __hogDateTime__: true, dt: start.getTime() / 1000, zone: (__isHogDateTime(value) ? value.zone : 'UTC') };
}
function toStartOfDay(value) {
    if (!__isHogDateTime(value) && !__isHogDate(value)) {
        throw new Error('Expected HogDate or HogDateTime for toStartOfDay');
    }
    if (__isHogDate(value)) {
        value = __toHogDateTime(Date.UTC(value.year, value.month-1, value.day)/1000, 'UTC');
    }
    return dateTrunc('day', value);
}
function toMonth(value) { return extract('month', value) }
function toIntervalMonth(val) { return __toHogInterval(val, 'month') }
function toIntervalDay(val) { return __toHogInterval(val, 'day') }
function toDateTime (input, zone) { return __toDateTime(input, zone) }
function toDate (input) { return __toDate(input) }
function substring(s, start, optionalLength) {
    if (typeof s !== 'string') return '';
    const startIdx = start - 1;
    const length = typeof optionalLength === 'number' ? optionalLength : s.length - startIdx;
    if (startIdx < 0 || length < 0) return '';
    const endIdx = startIdx + length;
    return startIdx < s.length ? s.slice(startIdx, endIdx) : '';
}
function startsWith(str, prefix) {
    return typeof str === 'string' && typeof prefix === 'string' && str.startsWith(prefix);
}
function round(a) { return Math.round(a) }
function reverse (value) { return value.split('').reverse().join('') }
function replaceOne (str, searchValue, replaceValue) { return str.replace(searchValue, replaceValue) }
function replaceAll (str, searchValue, replaceValue) { return str.replaceAll(searchValue, replaceValue) }
function range(...args) {
    if (args.length === 1) {
        const end = args[0];
        return Array.from({length:end}, (_,i)=>i);
    } else {
        const start = args[0];
        const end = args[1];
        return Array.from({length:end - start}, (_,i)=>start+i);
    }
}
function print (...args) { console.log(...args.map(__printHogStringOutput)) }
function plus(a, b) { return a + b }
function or(...args) { return args.some(Boolean) }
function now () { return __now() }
function notEquals(a, b) { return a !== b }
function notEmpty (value) { return !empty(value) }
function minus(a, b) { return a - b }
function min2(a, b) { return a < b ? a : b }
function lower (value) { if (value === null || value === undefined) { return null } return value.toLowerCase() }
function lessOrEquals(a, b) { return a <= b }
function less(a, b) { return a < b }
function length (value) { return value.length }
function jsonStringify (value, spacing) {
    function convert(x, marked) {
        if (!marked) { marked = new Set() }
        if (typeof x === 'object' && x !== null) {
            if (marked.has(x)) { return null }
            marked.add(x)
            try {
                if (x instanceof Map) {
                    const obj = {}
                    x.forEach((value, key) => { obj[convert(key, marked)] = convert(value, marked) })
                    return obj
                }
                if (Array.isArray(x)) { return x.map((v) => convert(v, marked)) }
                if (__isHogDateTime(x) || __isHogDate(x) || __isHogError(x)) { return x }
                if (typeof x === 'function') { return `fn<${x.name || 'lambda'}(${x.length})>` }
                const obj = {}; for (const key in x) { obj[key] = convert(x[key], marked) }
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
    return JSON.stringify(convert(value), (key, val) => typeof val === 'function' ? `fn<${val.name || 'lambda'}(${val.length})>` : val)
}
function isNull (value) { return value === null || value === undefined }
function isNotNull (value) { return value !== null && value !== undefined }
function __x_in(val, arr) {
    if (Array.isArray(arr) || (arr && arr.__isHogTuple)) {
        return arr.includes(val);
    }
    return false;
}
function greaterOrEquals(a, b) { return a >= b }
function greater(a, b) { return a > b }
function generateUUIDv4 () { return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function (c) { const r = (Math.random() * 16) | 0; const v = c === 'x' ? r : (r & 0x3) | 0x8; return v.toString(16) })}
function floor(a) { return Math.floor(a) }
function extract(part, val) {
    function toDate(obj) {
        if (__isHogDateTime(obj)) {
            return new Date(obj.dt * 1000);
        } else if (__isHogDate(obj)) {
            return new Date(Date.UTC(obj.year, obj.month - 1, obj.day));
        } else {
            return new Date(obj);
        }
    }
    const date = toDate(val);
    if (part === 'year') return date.getUTCFullYear();
    else if (part === 'month') return date.getUTCMonth() + 1;
    else if (part === 'day') return date.getUTCDate();
    else if (part === 'hour') return date.getUTCHours();
    else if (part === 'minute') return date.getUTCMinutes();
    else if (part === 'second') return date.getUTCSeconds();
    else throw new Error("Unknown extract part: " + part);
}
function equals(a, b) { return a === b }
function encodeURLComponent (str) { return encodeURIComponent(str) }
function empty (value) {
    if (typeof value === 'object') {
        if (Array.isArray(value)) { return value.length === 0 } else if (value === null) { return true } else if (value instanceof Map) { return value.size === 0 }
        return Object.keys(value).length === 0
    } else if (typeof value === 'number' || typeof value === 'boolean') { return false }
    return !value }
function decodeURLComponent (str) { return decodeURIComponent(str) }
function dateTrunc(unit, val) {
    if (!__isHogDateTime(val)) {
        throw new Error('Expected a DateTime for dateTrunc');
    }
    const zone = val.zone || 'UTC';
    const date = new Date(val.dt * 1000);
    let year = date.getUTCFullYear();
    let month = date.getUTCMonth();
    let day = date.getUTCDate();
    let hour = date.getUTCHours();
    let minute = date.getUTCMinutes();
    let second = 0;
    let ms = 0;

    if (unit === 'year') {
        month = 0; day = 1; hour = 0; minute = 0; second = 0;
    } else if (unit === 'month') {
        day = 1; hour = 0; minute = 0; second = 0;
    } else if (unit === 'day') {
        hour = 0; minute = 0; second = 0;
    } else if (unit === 'hour') {
        minute = 0; second = 0;
    } else if (unit === 'minute') {
        second = 0;
    } else {
        throw new Error("Unsupported unit for dateTrunc: " + unit);
    }

    const truncated = new Date(Date.UTC(year, month, day, hour, minute, second, ms));
    return { __hogDateTime__: true, dt: truncated.getTime()/1000, zone: zone };
}
function dateDiff(unit, startVal, endVal) {
    function toDateTime(obj) {
        if (__isHogDateTime(obj)) {
            return new Date(obj.dt * 1000);
        } else if (__isHogDate(obj)) {
            return new Date(Date.UTC(obj.year, obj.month - 1, obj.day));
        } else {
            return new Date(obj);
        }
    }
    const start = toDateTime(startVal);
    const end = toDateTime(endVal);
    const diffMs = end - start;
    const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));
    if (unit === 'day') {
        return diffDays;
    } else if (unit === 'hour') {
        return Math.floor(diffMs / (1000 * 60 * 60));
    } else if (unit === 'minute') {
        return Math.floor(diffMs / (1000 * 60));
    } else if (unit === 'second') {
        return Math.floor(diffMs / 1000);
    } else if (unit === 'week') {
        return Math.floor(diffDays / 7);
    } else if (unit === 'month') {
        // Approx months difference
        const sy = start.getUTCFullYear();
        const sm = start.getUTCMonth() + 1;
        const ey = end.getUTCFullYear();
        const em = end.getUTCMonth() + 1;
        return (ey - sy)*12 + (em - sm);
    } else if (unit === 'year') {
        return end.getUTCFullYear() - start.getUTCFullYear();
    } else {
        throw new Error("Unsupported unit for dateDiff: " + unit);
    }
}
function dateAdd(unit, amount, datetime) {
    // transform unit if needed (week -> day, year -> month)
    if (unit === 'week') {
        unit = 'day';
        amount = amount * 7;
    } else if (unit === 'year') {
        unit = 'month';
        amount = amount * 12;
    }
    const interval = __toHogInterval(amount, unit);
    return __applyIntervalToDateTime(datetime, interval);
}
function coalesce(...args) {
    for (let a of args) {
        if (a !== null && a !== undefined) return a;
    }
    return null;
}
function base64Encode (str) { return Buffer.from(str).toString('base64') }
function base64Decode (str) { return Buffer.from(str, 'base64').toString() }
function assumeNotNull(value) {
    if (value === null || value === undefined) {
        throw new Error("Value is null in assumeNotNull");
    }
    return value;
}
function and(...args) { return args.every(Boolean) }
function addDays(dateOrDt, days) {
    const interval = __toHogInterval(days, 'day');
    return __applyIntervalToDateTime(dateOrDt, interval);
}
function __toHogInterval(value, unit) {
    return { __hogInterval__: true, value: value, unit: unit };
}
function __toDateTime(input, zone) { let dt;
    if (typeof input === 'number') { dt = input; }
    else { const date = new Date(input); if (isNaN(date.getTime())) { throw new Error('Invalid date input'); } dt = date.getTime() / 1000; }
    return { __hogDateTime__: true, dt: dt, zone: zone || 'UTC' }; }
function __toDate(input) { let date;
    if (typeof input === 'number') { date = new Date(input * 1000); } else { date = new Date(input); }
    if (isNaN(date.getTime())) { throw new Error('Invalid date input'); }
    return { __hogDate__: true, year: date.getUTCFullYear(), month: date.getUTCMonth() + 1, day: date.getUTCDate() }; }
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
function __now(zone) { return __toHogDateTime(Date.now() / 1000, zone) }
function __isHogError(obj) {return obj && obj.__hogError__ === true}
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
function __applyIntervalToDateTime(base, interval) {
    // base can be HogDate or HogDateTime
    if (!(__isHogDate(base) || __isHogDateTime(base))) {
        throw new Error("Expected a HogDate or HogDateTime");
    }

    let zone = __isHogDateTime(base) ? (base.zone || 'UTC') : 'UTC';

    function toDate(obj) {
        if (__isHogDateTime(obj)) {
            return new Date(obj.dt * 1000);
        } else {
            return new Date(Date.UTC(obj.year, obj.month - 1, obj.day));
        }
    }

    const dt = toDate(base);
    const value = interval.value;
    let unit = interval.unit;

    // Expand weeks/years if needed
    if (unit === 'week') {
        unit = 'day';
        interval.value = value * 7;
    } else if (unit === 'year') {
        unit = 'month';
        interval.value = value * 12;
    }

    let year = dt.getUTCFullYear();
    let month = dt.getUTCMonth() + 1;
    let day = dt.getUTCDate();
    let hours = dt.getUTCHours();
    let minutes = dt.getUTCMinutes();
    let seconds = dt.getUTCSeconds();
    let ms = dt.getUTCMilliseconds();

    if (unit === 'day') {
        day += interval.value;
    } else if (unit === 'hour') {
        hours += interval.value;
    } else if (unit === 'minute') {
        minutes += interval.value;
    } else if (unit === 'second') {
        seconds += interval.value;
    } else if (unit === 'month') {
        month += interval.value;
        // Adjust year and month
        year += Math.floor((month - 1) / 12);
        month = ((month - 1) % 12) + 1;
        // If day is invalid for the new month, clamp it
        let maxDay = new Date(Date.UTC(year, month, 0)).getUTCDate();
        if (day > maxDay) { day = maxDay; }
    } else {
        throw new Error("Unsupported interval unit: " + unit);
    }

    const newDt = new Date(Date.UTC(year, month - 1, day, hours, minutes, seconds, ms));

    if (__isHogDate(base)) {
        return __toHogDate(newDt.getUTCFullYear(), newDt.getUTCMonth() + 1, newDt.getUTCDate());
    } else {
        return __toHogDateTime(newDt.getTime() / 1000, zone);
    }
}
function __toHogDateTime(timestamp, zone) {
    if (__isHogDate(timestamp)) {
        const date = new Date(Date.UTC(timestamp.year, timestamp.month - 1, timestamp.day));
        const dt = date.getTime() / 1000;
        return { __hogDateTime__: true, dt: dt, zone: zone || 'UTC' };
    }
    return { __hogDateTime__: true, dt: timestamp, zone: zone || 'UTC' }; }
function __toHogDate(year, month, day) { return { __hogDate__: true, year: year, month: month, day: day, } }
function __isHogDateTime(obj) { return obj && obj.__hogDateTime__ === true }
function __isHogDate(obj) { return obj && obj.__hogDate__ === true }
function JSONExtractString(obj, ...path) {
    try {
        if (typeof obj === 'string') { obj = JSON.parse(obj); }
    } catch (e) { return null; }
    const val = __getNestedValue(obj, path, true);
    return val != null ? String(val) : null;
}
function JSONExtractInt(obj, ...path) {
    try {
        if (typeof obj === 'string') { obj = JSON.parse(obj); }
    } catch (e) { return null; }
    const val = __getNestedValue(obj, path, true);
    const i = parseInt(val);
    return isNaN(i) ? null : i;
}
function JSONExtractFloat(obj, ...path) {
    try {
        if (typeof obj === 'string') { obj = JSON.parse(obj); }
    } catch (e) { return null; }
    const val = __getNestedValue(obj, path, true);
    const f = parseFloat(val);
    return isNaN(f) ? null : f;
}
function JSONExtractArrayRaw(obj, ...path) {
    try {
        if (typeof obj === 'string') { obj = JSON.parse(obj); }
    } catch (e) { return null; }
    const val = __getNestedValue(obj, path, true);
    return Array.isArray(val) ? val : null;
}
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

print("-- empty, notEmpty, length, lower, upper, reverse --");
if (!!(empty("") && notEmpty("234"))) {
    print(length("123"));
}
if ((lower("Tdd4gh") == "tdd4gh")) {
    print(upper("test"));
}
print(lower(null));
print(reverse("spinner"));
print("");
print("-- encodeURLComponent, decodeURLComponent --");
print(encodeURLComponent("http://www.google.com"));
print(encodeURLComponent("tom & jerry"));
print(decodeURLComponent(encodeURLComponent("http://www.google.com")));
print(decodeURLComponent(encodeURLComponent("tom & jerry")));
print("");
print("-- base64Encode, base64Decode --");
print(base64Encode("http://www.google.com"));
print(base64Encode("tom & jerry"));
print(base64Decode(base64Encode("http://www.google.com")));
print(base64Decode(base64Encode("tom & jerry")));
print("");
print("-- empty --");
print(empty(null));
print(empty(0));
print(empty(1));
print(empty(-1));
print(empty(0.0));
print(empty(0.01));
print(empty(""));
print(empty("string"));
print(empty("0"));
print(empty([]));
print(empty({}));
print(empty(tuple()));
print(empty(tuple(0)));
print(empty(tuple(1, 2)));
print(empty(true));
print(empty(false));
print("");
print("-- notEmpty --");
print(notEmpty(null));
print(notEmpty(0));
print(notEmpty(1));
print(notEmpty(-1));
print(notEmpty(0.0));
print(notEmpty(0.01));
print(notEmpty(""));
print(notEmpty("string"));
print(notEmpty("0"));
print(notEmpty([]));
print(notEmpty({}));
print(notEmpty(tuple()));
print(notEmpty(tuple(0)));
print(notEmpty(tuple(1, 2)));
print(notEmpty(true));
print(notEmpty(false));
print("");
print("-- replaceAll, replaceOne --");
print(replaceAll("hello world", "l", "L"));
print(replaceOne("hello world", "l", "L"));
print("");
print("-- generateUUIDv4 --");
print(length(generateUUIDv4()));
print("");
print("-- isNull, isNotNull --");
print(isNull(null), isNotNull(null));
print(isNull(true), isNotNull(true));
print(isNull("banana"), isNotNull("banana"));
print(isNull(false), isNotNull(false));
print(isNull(0), isNotNull(0));
print(isNull(1), isNotNull(1));
print("");
print("-- comparisons --");
print(equals(1, 1), equals(1, 2), equals(1, "1"));
print(notEquals(2, 3), (!true));
print(greater(2, 1), greaterOrEquals(2, 2));
print(less(1, 2), lessOrEquals(2, 2), less(-3, 2));
print(!!(false || true), !!(0 || 0), !!(1 || 0), !!(1 || false), !!(0 || false), or(1), or("string"), or(100));
print(!!(false && true), !!(0 && 0), !!(1 && 0), !!(1 && false), !!(0 && false), !!(1 && 1), and(1), and(true), and("string"), and(100));
print("");
print("-- logic --");
print((true ? "yes" : "no"), (false ? "yes" : "no"));
print((true ? "one" : (false ? "two" : "default")));
print("");
print("-- math --");
print(min2(3, 5));
print(plus(10, 5), minus(10, 5));
print(floor(3.99), round(3.5));
print(range(5));
print(range(3, 6));
print("");
print("-- string/array --");
print(__x_in("a", tuple("a", "b", "c")), __x_in("z", tuple("a", "b", "c")));
print(__x_in("a", ["a", "b", "c"]), __x_in("z", ["a", "b", "c"]));
print(startsWith("hello", "he"), substring("abcdef", 2, 3));
print(substring("abcdef", 2));
print(coalesce(null, null, "firstNonNull"), assumeNotNull("notNull"));
print("");
print("-- date --");
print(toYear(toDateTime("2024-12-18T00:00:00Z")), toMonth(toDateTime("2024-12-18T00:00:00Z")));
print(__x_typeof(now()));
print(toStartOfDay(toDateTime("2024-12-18T11:11:11Z")), toStartOfWeek(toDateTime("2024-12-18T11:11:11Z")));
print(toYYYYMM(toDateTime("2024-12-18T00:00:00Z")));
print(dateAdd("day", 1, toDate("2024-12-18")), dateDiff("day", toDate("2024-12-18"), dateAdd("day", 5, toDate("2024-12-18"))));
print(dateTrunc("day", toDateTime("2024-12-18T12:34:56Z")));
print(addDays(toDate("2024-12-18"), 3));
print(toIntervalDay(5), toIntervalMonth(2));
print(__x_typeof(today()));
print("");
print("-- json --");
print(jsonStringify(JSONExtractInt("{\"a\":123.1}", "a")), jsonStringify(JSONExtractInt("{\"a\":\"hello\"}", "a")));
print(jsonStringify(JSONExtractFloat("{\"a\":123.1}", "a")), jsonStringify(JSONExtractFloat("{\"a\":\"hello\"}", "a")));
print(jsonStringify(JSONExtractString("{\"a\":123.1}", "a")), jsonStringify(JSONExtractString("{\"a\":\"hello\"}", "a")));
print(jsonStringify(JSONExtractArrayRaw("{\"a\":123}", "a")), jsonStringify(JSONExtractArrayRaw("{\"a\":\"hello\"}", "a")));
print(jsonStringify(JSONExtractArrayRaw("{\"a\":[]}", "a")), jsonStringify(JSONExtractArrayRaw("{\"a\":[\"hello\"]}", "a")));
