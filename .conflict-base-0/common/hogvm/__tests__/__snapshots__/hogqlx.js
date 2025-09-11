function replaceAll (str, searchValue, replaceValue) { return str.replaceAll(searchValue, replaceValue) }
function print (...args) { console.log(...args.map(__printHogStringOutput)) }
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
function __lambda (fn) { return fn }
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

let printQ = __lambda((q) => print(replaceAll(jsonStringify(q), " ", "")));
let Hello = __lambda((props) => ({"__hx_tag": "span", "children": ["hello: ", __getProperty(props, "value", true)]}));
print(Hello({"value": "world"}));
print(Hello({"value": "world"}));
print({"__hx_tag": "hr"});
let b = {"__hx_tag": "div", "children": ["outer. ", Hello({"value": "hello"})]};
print(b);
print({"__hx_tag": "hr"});
let Filter = __lambda((props) => {
    let query = {"__hx_ast": "Constant", "value": true};
    if (__getProperty(props, "name", true)) {
            query = {"__hx_ast": "And", "exprs": [query, {"__hx_ast": "CompareOperation", "left": {"__hx_ast": "Field", "chain": ["properties", "name"]}, "right": __getProperty(props, "name", true), "op": "=="}]}
        }
    if (__getProperty(props, "email", true)) {
            query = {"__hx_ast": "And", "exprs": [query, {"__hx_ast": "CompareOperation", "left": {"__hx_ast": "Field", "chain": ["properties", "email"]}, "right": __getProperty(props, "email", true), "op": "=="}]}
        }
    return query;
});
let query1 = Filter({"name": "John", "email": "john@gmail.com"});
printQ(query1);
let query2 = {"__hx_ast": "And", "exprs": [{"__hx_ast": "Constant", "value": true}, Filter({"name": {"__hx_ast": "Constant", "value": "John"}, "email": {"__hx_ast": "Constant", "value": "john@gmail.com"}})]};
printQ(query2);
let query3a = {"__hx_ast": "SelectQuery", "select": [{"__hx_ast": "Alias", "alias": "name", "expr": {"__hx_ast": "Field", "chain": ["properties", "name"]}, "hidden": false}, {"__hx_ast": "Alias", "alias": "email", "expr": {"__hx_ast": "Call", "name": "distinct", "args": [{"__hx_ast": "Field", "chain": ["properties", "email"]}], "distinct": false}, "hidden": false}], "distinct": true, "select_from": {"__hx_ast": "JoinExpr", "table": {"__hx_ast": "Field", "chain": ["events"]}}, "where": Filter({"name": "John", "email": "john@gmail.com"})};
let query3b = {"__hx_ast": "SelectQuery", "select": [{"__hx_ast": "Alias", "alias": "name", "expr": {"__hx_ast": "Field", "chain": ["properties", "name"]}, "hidden": false}, {"__hx_ast": "Alias", "alias": "email", "expr": {"__hx_ast": "Call", "name": "distinct", "args": [{"__hx_ast": "Field", "chain": ["properties", "email"]}], "distinct": false}, "hidden": false}], "distinct": true, "select_from": {"__hx_ast": "JoinExpr", "table": {"__hx_ast": "Field", "chain": ["events"]}}, "where": Filter({"name": {"__hx_ast": "Constant", "value": "John"}, "email": {"__hx_ast": "Constant", "value": "john@gmail.com"}})};
printQ(query3a);
printQ(query3b);
print(((jsonStringify(query3b).includes("HogQLXAttribute")) ? "FAILED" : "PASSED"));
