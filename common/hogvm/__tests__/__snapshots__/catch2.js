function print (...args) { console.log(...args.map(__printHogStringOutput)) }
function concat (...args) { return args.map((arg) => (arg === null ? '' : __STLToString(arg))).join('') }
function __getProperty(objectOrArray, key, nullish) {
    if ((nullish && !objectOrArray) || key === 0) { return null }
    if (Array.isArray(objectOrArray)) { return key > 0 ? objectOrArray[key - 1] : objectOrArray[objectOrArray.length + key] }
    else { return objectOrArray[key] }
}
function __STLToString(arg) {
    if (arg && __isHogDate(arg)) { return `${arg.year}-${arg.month.toString().padStart(2, '0')}-${arg.day.toString().padStart(2, '0')}`; }
    else if (arg && __isHogDateTime(arg)) { return __DateTimeToString(arg); }
    return __printHogStringOutput(arg); }
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
function __isHogDateTime(obj) { return obj && obj.__hogDateTime__ === true }
function __isHogDate(obj) { return obj && obj.__hogDate__ === true }
function __DateTimeToString(dt) {
    if (__isHogDateTime(dt)) {
        const date = new Date(dt.dt * 1000);
        const timeZone = dt.zone || 'UTC';
        const milliseconds = Math.floor(dt.dt * 1000 % 1000);
        const options = { timeZone, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false };
        const formatter = new Intl.DateTimeFormat('en-US', options);
        const parts = formatter.formatToParts(date);
        let year, month, day, hour, minute, second;
        for (const part of parts) {
            switch (part.type) {
                case 'year': year = part.value; break;
                case 'month': month = part.value; break;
                case 'day': day = part.value; break;
                case 'hour': hour = part.value; break;
                case 'minute': minute = part.value; break;
                case 'second': second = part.value; break;
                default: break;
            }
        }
        const getOffset = (date, timeZone) => {
            const tzDate = new Date(date.toLocaleString('en-US', { timeZone }));
            const utcDate = new Date(date.toLocaleString('en-US', { timeZone: 'UTC' }));
            const offset = (tzDate - utcDate) / 60000; // in minutes
            const sign = offset >= 0 ? '+' : '-';
            const absOffset = Math.abs(offset);
            const hours = Math.floor(absOffset / 60);
            const minutes = absOffset % 60;
            return `${sign}${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}`;
        };
        let offset = 'Z';
        if (timeZone !== 'UTC') {
            offset = getOffset(date, timeZone);
        }
        let isoString = `${year}-${month}-${day}T${hour}:${minute}:${second}`;
        isoString += `.${milliseconds.toString().padStart(3, '0')}`;
        isoString += offset;
        return isoString;
    }
}
function HogError (type, message, payload) { return __newHogError(type, message, payload) }
function __newHogError(type, message, payload) {
    let error = new Error(message || 'An error occurred');
    error.__hogError__ = true
    error.type = type
    error.payload = payload
    return error
}

try {
    try {
            throw HogError("FishError", "You forgot to feed your fish");
        } catch (__error) { if (__error.type === "FoodError") { let e = __error;
        print(concat("Problem with your food: ", __getProperty(e, "message", true)));
    }
     else { throw __error; }}
} catch (__error) { if (__error.type === "FishError") { let e = __error;
print(concat("FishError: ", __getProperty(e, "message", true)));
}
 else if (true) { let e = __error;
print(concat("Error: ", __getProperty(e, "message", true)));
}
}
try {
    try {
            throw HogError("FunkyError", "You forgot to feed your fish");
        } catch (__error) { if (__error.type === "FoodError") { let e = __error;
        print(concat("Problem with your food: ", __getProperty(e, "message", true)));
    }
     else { throw __error; }}
} catch (__error) { if (__error.type === "FishError") { let e = __error;
print(concat("FishError: ", __getProperty(e, "message", true)));
}
 else if (true) { let e = __error;
print(concat("Error of type ", __getProperty(e, "type", true), ": ", __getProperty(e, "message", true)));
}
}
try {
    try {
            throw HogError("FishError", "You forgot to feed your fish");
        } catch (__error) { if (__error.type === "FoodError") { let e = __error;
        print(concat("Problem with your food: ", __getProperty(e, "message", true)));
    }
     else { throw __error; }}
} catch (__error) { if (true) { let e = __error;
print(concat("Error of type ", __getProperty(e, "type", true), ": ", __getProperty(e, "message", true)));
}
 else if (__error.type === "FishError") { let e = __error;
print(concat("FishError: ", __getProperty(e, "message", true)));
}
}
