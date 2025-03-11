function toUnixTimestampMilli (input, zone) { return __toUnixTimestampMilli(input, zone) }
function toUnixTimestamp (input, zone) { return __toUnixTimestamp(input, zone) }
function toTimeZone (input, zone) { return __toTimeZone(input, zone) }
function toString (value) { return __STLToString(value) }
function toInt(value) {
    if (__isHogDateTime(value)) { return Math.floor(value.dt); }
    else if (__isHogDate(value)) { const date = new Date(Date.UTC(value.year, value.month - 1, value.day)); const epoch = new Date(Date.UTC(1970, 0, 1)); const diffInDays = Math.floor((date - epoch) / (1000 * 60 * 60 * 24)); return diffInDays; }
    return !isNaN(parseInt(value)) ? parseInt(value) : null; }
function toFloat(value) {
    if (__isHogDateTime(value)) { return value.dt; }
    else if (__isHogDate(value)) { const date = new Date(Date.UTC(value.year, value.month - 1, value.day)); const epoch = new Date(Date.UTC(1970, 0, 1)); const diffInDays = (date - epoch) / (1000 * 60 * 60 * 24); return diffInDays; }
    return !isNaN(parseFloat(value)) ? parseFloat(value) : null; }
function toDateTime (input, zone) { return __toDateTime(input, zone) }
function toDate (input) { return __toDate(input) }
function print (...args) { console.log(...args.map(__printHogStringOutput)) }
function fromUnixTimestampMilli (input) { return __fromUnixTimestampMilli(input) }
function fromUnixTimestamp (input) { return __fromUnixTimestamp(input) }
function __toUnixTimestampMilli(input, zone) { return __toUnixTimestamp(input, zone) * 1000 }
function __toUnixTimestamp(input, zone) {
    if (__isHogDateTime(input)) { return input.dt; }
    if (__isHogDate(input)) { return __toHogDateTime(input).dt; }
    const date = new Date(input);
    if (isNaN(date.getTime())) { throw new Error('Invalid date input'); }
    return Math.floor(date.getTime() / 1000);}
function __toTimeZone(input, zone) { if (!__isHogDateTime(input)) { throw new Error('Expected a DateTime') }; return { ...input, zone }}
function __toDateTime(input, zone) { let dt;
    if (typeof input === 'number') { dt = input; }
    else { const date = new Date(input); if (isNaN(date.getTime())) { throw new Error('Invalid date input'); } dt = date.getTime() / 1000; }
    return { __hogDateTime__: true, dt: dt, zone: zone || 'UTC' }; }
function __toDate(input) { let date;
    if (typeof input === 'number') { date = new Date(input * 1000); } else { date = new Date(input); }
    if (isNaN(date.getTime())) { throw new Error('Invalid date input'); }
    return { __hogDate__: true, year: date.getUTCFullYear(), month: date.getUTCMonth() + 1, day: date.getUTCDate() }; }
function __fromUnixTimestampMilli(input) { return __toHogDateTime(input / 1000) }
function __fromUnixTimestamp(input) { return __toHogDateTime(input) }
function __toHogDateTime(timestamp, zone) {
    if (__isHogDate(timestamp)) {
        const date = new Date(Date.UTC(timestamp.year, timestamp.month - 1, timestamp.day));
        const dt = date.getTime() / 1000;
        return { __hogDateTime__: true, dt: dt, zone: zone || 'UTC' };
    }
    return { __hogDateTime__: true, dt: timestamp, zone: zone || 'UTC' }; }
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

let dt = fromUnixTimestamp(1234334543);
print(dt);
print(toString(dt));
print(toInt(toUnixTimestamp(dt)));
print("-");
let dt2 = toDate("2024-05-03");
print(dt2);
print(toString(dt2));
print(toInt(toUnixTimestamp(dt2)));
print("-");
let dt3 = toDateTime("2024-05-03T12:34:56Z");
print(dt3);
print(toString(dt3));
print(toInt(toUnixTimestamp(dt3)));
print("------");
print(toTimeZone(dt3, "Europe/Brussels"));
print(toString(toTimeZone(dt3, "Europe/Brussels")));
print("-");
print(toTimeZone(dt3, "Europe/Tallinn"));
print(toString(toTimeZone(dt3, "Europe/Tallinn")));
print("-");
print(toTimeZone(dt3, "America/New_York"));
print(toString(toTimeZone(dt3, "America/New_York")));
print("------");
let timestamp = fromUnixTimestamp(1234334543.123);
print("timestamp:                                ", timestamp);
print("toString(timestamp):                      ", toString(timestamp));
print("toInt(timestamp):                         ", toInt(timestamp));
print("toDateTime(toInt(timestamp)):             ", toDateTime(toInt(timestamp)));
print("toInt(toDateTime(toInt(timestamp))):      ", toInt(toDateTime(toInt(timestamp))));
print("toString(toDateTime(toInt(timestamp))):   ", toString(toDateTime(toInt(timestamp))));
print("toFloat(timestamp):                       ", toFloat(timestamp));
print("toDateTime(toFloat(timestamp)):           ", toDateTime(toFloat(timestamp)));
print("toFloat(toDateTime(toFloat(timestamp))):  ", toFloat(toDateTime(toFloat(timestamp))));
print("toString(toDateTime(toFloat(timestamp))): ", toString(toDateTime(toFloat(timestamp))));
print("------");
let millisTs = fromUnixTimestampMilli(1234334543123);
print("millisTs:                                 ", toString(millisTs));
print("toString(millisTs):                       ", toString(millisTs));
print("toInt(millisTs):                          ", toInt(millisTs));
print("toFloat(millisTs):                        ", toFloat(millisTs));
print("toUnixTimestampMilli(millisTs):           ", toUnixTimestampMilli(millisTs));
print("------");
let date = toDate("2024-05-03");
print(date);
print(toString(date));
print(toInt(date));
