function print (...args) { console.log(...args.map(__printHogStringOutput)) }
function isIPAddressInRange(address, prefix) {
    function toBytes(ip, isV4) {
        if (isV4) {
            const p = ip.split('.')
            if (p.length !== 4) return null

            const b = new Uint8Array(4)
            for (let i = 0; i < 4; i++) {
                const n = +p[i]
                if (isNaN(n) || n < 0 || n > 255 || p[i] !== n.toString()) return null
                b[i] = n
            }
            return b
        }

        const b = new Uint8Array(16)
        let s

        if (ip.includes('::')) {
            if ((ip.match(/::/g) || []).length > 1) return null

            const [pre, post] = ip.split('::')
            const preSeg = pre ? pre.split(':') : []
            const postSeg = post ? post.split(':') : []

            if (preSeg.length + postSeg.length > 7) return null

            s = [...preSeg, ...Array(8 - preSeg.length - postSeg.length).fill('0'), ...postSeg]
        } else {
            s = ip.split(':')
            if (s.length !== 8) return null
        }

        for (let i = 0; i < 8; i++) {
            if (!s[i] && s[i] !== '0') return null

            const v = parseInt(s[i], 16)
            if (isNaN(v) || v < 0 || v > 0xffff) return null

            b[i * 2] = v >> 8
            b[i * 2 + 1] = v & 0xff
        }
        return b
    }

    try {
        if (!address || !prefix) return false

        const [net, mask] = prefix.split('/')
        if (!net || !mask) return false

        const cidr = +mask
        if (isNaN(cidr) || cidr < 0) return false

        const v4 = address.includes('.') && net.includes('.')
        const v6 = !v4 && address.includes(':') && net.includes(':')
        if (!v4 && !v6) return false
        if ((v4 && cidr > 32) || (v6 && cidr > 128)) return false

        const aBytes = toBytes(address, v4)
        const nBytes = toBytes(net, v4)
        if (!aBytes || !nBytes) return false

        const fullBytes = cidr >> 3
        for (let i = 0; i < fullBytes; i++) if (aBytes[i] !== nBytes[i]) return false

        const bits = cidr & 7
        if (bits && fullBytes < aBytes.length) {
            const m = 0xff << (8 - bits)
            if ((aBytes[fullBytes] & m) !== (nBytes[fullBytes] & m)) return false
        }

        return true
    } catch {
        return false
    }
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

print(isIPAddressInRange("192.168.1.1", "192.168.1.1/32"));
print(isIPAddressInRange("192.168.1.5", "192.168.1.0/24"));
print(isIPAddressInRange("192.168.1.5", "192.0.0.0/8"));
print(isIPAddressInRange("192.168.1.5", "192.168.2.0/24"));
print(isIPAddressInRange("192.168.1.255", "192.168.1.0/24"));
print(isIPAddressInRange("192.168.1.0", "192.168.1.0/24"));
print(isIPAddressInRange("8.8.8.8", "0.0.0.0/0"));
print(isIPAddressInRange("192.168.1.1", "192.168.1.1/32"));
print(isIPAddressInRange("192.168.1.2", "192.168.1.1/32"));
print(isIPAddressInRange("2001:db8::1", "2001:db8::1/128"));
print(isIPAddressInRange("2001:db8::1:5", "2001:db8::1:0/112"));
print(isIPAddressInRange("2001:db8::1:5", "2001:db8::/32"));
print(isIPAddressInRange("2001:db8:1::5", "2001:db8:2::/48"));
print(isIPAddressInRange("2001:db8::ffff", "2001:db8::/64"));
print(isIPAddressInRange("2001:db8::", "2001:db8::/64"));
print(isIPAddressInRange("2001:db8::1", "::/0"));
print(isIPAddressInRange("2001:db8::1", "2001:db8:0:0:0:0:0:0/64"));
print(isIPAddressInRange("2001:db8:0:0:0:0:0:1", "2001:db8::/64"));
print(isIPAddressInRange("2001:db8::1", "2001:db8::1/128"));
print(isIPAddressInRange("2001:db8::2", "2001:db8::1/128"));
print(isIPAddressInRange(null, "192.168.1.0/24"));
print(isIPAddressInRange("192.168.1.1", null));
print(isIPAddressInRange("", "192.168.1.0/24"));
print(isIPAddressInRange("192.168.1.1", ""));
print(isIPAddressInRange("192.168.1.1", "192.168.1.0"));
print(isIPAddressInRange("192.168.1.1", "192.168.1.0/"));
print(isIPAddressInRange("192.168.1.1", "/24"));
print(isIPAddressInRange("192.168.1.1", "192.168.1.0/33"));
print(isIPAddressInRange("2001:db8::1", "2001:db8::/129"));
print(isIPAddressInRange("192.168.1.1", "192.168.1.0/-1"));
print(isIPAddressInRange("192.168.1.1", "192.168.1.0/abc"));
print(isIPAddressInRange("192.168.1", "192.168.1.0/24"));
print(isIPAddressInRange("192.168.1.1.5", "192.168.1.0/24"));
print(isIPAddressInRange("192.168.1.256", "192.168.1.0/24"));
print(isIPAddressInRange("192.168.1.a", "192.168.1.0/24"));
print(isIPAddressInRange("2001:db8", "2001:db8::/32"));
print(isIPAddressInRange("2001:db8:::1", "2001:db8::/32"));
print(isIPAddressInRange("2001:db8:gggg::1", "2001:db8::/32"));
print(isIPAddressInRange("2001:db8::1::2", "2001:db8::/32"));
print(isIPAddressInRange("192.168.1.1", "2001:db8::/32"));
print(isIPAddressInRange("2001:db8::1", "192.168.1.0/24"));
print(isIPAddressInRange(123, "192.168.1.0/24"));
print(isIPAddressInRange("192.168.1.1", 24));
print(isIPAddressInRange("127.0.0.1", "127.0.0.0/8"));
print(isIPAddressInRange("255.255.255.255", "0.0.0.0/0"));
print(isIPAddressInRange("::1", "::1/128"));
print(isIPAddressInRange("fe80::1", "fe80::/10"));
