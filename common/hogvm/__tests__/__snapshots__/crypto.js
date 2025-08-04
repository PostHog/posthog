function sha256HmacChainHex (data, options) { return 'sha256HmacChainHex not implemented' }
function sha256HmacChain (data, encoding, options) { return 'sha256HmacChain not implemented' }
function sha256Hex(data) {if (data === null || data == undefined) return null; let h0=0x6a09e667,h1=0xbb67ae85,h2=0x3c6ef372,h3=0xa54ff53a,h4=0x510e527f,h5=0x9b05688c,h6=0x1f83d9ab,h7=0x5be0cd19,tsz=0,bp=0;const k=[0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2],rrot=(x,n)=>(x>>>n)|(x<<(32-n)),w=new Uint32Array(64),buf=new Uint8Array(64),process=()=>{for(let j=0,r=0;j<16;j++,r+=4){w[j]=(buf[r]<<24)|(buf[r+1]<<16)|(buf[r+2]<<8)|buf[r+3]}for(let j=16;j<64;j++){let s0=rrot(w[j-15],7)^rrot(w[j-15],18)^(w[j-15]>>>3);let s1=rrot(w[j-2],17)^rrot(w[j-2],19)^(w[j-2]>>>10);w[j]=(w[j-16]+s0+w[j-7]+s1)|0}let a=h0,b=h1,c=h2,d=h3,e=h4,f=h5,g=h6,h=h7;for(let j=0;j<64;j++){let S1=rrot(e,6)^rrot(e,11)^rrot(e,25),ch=(e&f)^((~e)&g),t1=(h+S1+ch+k[j]+w[j])|0,S0=rrot(a,2)^rrot(a,13)^rrot(a,22),maj=(a&b)^(a&c)^(b&c),t2=(S0+maj)|0;h=g;g=f;f=e;e=(d+t1)|0;d=c;c=b;b=a;a=(t1+t2)|0}h0=(h0+a)|0;h1=(h1+b)|0;h2=(h2+c)|0;h3=(h3+d)|0;h4=(h4+e)|0;h5=(h5+f)|0;h6=(h6+g)|0;h7=(h7+h)|0;bp=0},add=data=>{if(typeof data==="string"){data=typeof TextEncoder==="undefined"?Buffer.from(data):(new TextEncoder).encode(data)}for(let i=0;i<data.length;i++){buf[bp++]=data[i];if(bp===64)process();}tsz+=data.length},digest=()=>{buf[bp++]=0x80;if(bp==64)process();if(bp+8>64){while(bp<64)buf[bp++]=0x00;process()}while(bp<58)buf[bp++]=0x00;let L=tsz*8;buf[bp++]=(L/1099511627776.)&255;buf[bp++]=(L/4294967296.)&255;buf[bp++]=L>>>24;buf[bp++]=(L>>>16)&255;buf[bp++]=(L>>>8)&255;buf[bp++]=L&255;process();let reply=new Uint8Array(32);reply[0]=h0>>>24;reply[1]=(h0>>>16)&255;reply[2]=(h0>>>8)&255;reply[3]=h0&255;reply[4]=h1>>>24;reply[5]=(h1>>>16)&255;reply[6]=(h1>>>8)&255;reply[7]=h1&255;reply[8]=h2>>>24;reply[9]=(h2>>>16)&255;reply[10]=(h2>>>8)&255;reply[11]=h2&255;reply[12]=h3>>>24;reply[13]=(h3>>>16)&255;reply[14]=(h3>>>8)&255;reply[15]=h3&255;reply[16]=h4>>>24;reply[17]=(h4>>>16)&255;reply[18]=(h4>>>8)&255;reply[19]=h4&255;reply[20]=h5>>>24;reply[21]=(h5>>>16)&255;reply[22]=(h5>>>8)&255;reply[23]=h5&255;reply[24]=h6>>>24;reply[25]=(h6>>>16)&255;reply[26]=(h6>>>8)&255;reply[27]=h6&255;reply[28]=h7>>>24;reply[29]=(h7>>>16)&255;reply[30]=(h7>>>8)&255;reply[31]=h7&255;reply.hex=()=>{let res="";reply.forEach(x=>res+=("0"+x.toString(16)).slice(-2));return res};return reply};if(data===undefined)return{add,digest};add(data);return digest().hex()}
function sha256 (data, encoding, options) { return 'sha256 not implemented' }
function print (...args) { console.log(...args.map(__printHogStringOutput)) }
function md5Hex(s) {if (s === null || s == undefined) return null; var k=[],i=0;for(;i<64;){k[i]=0|Math.sin(++i%Math.PI)*4294967296}var b,c,d,h=[b=0x67452301,c=0xEFCDAB89,~b,~c],words=[],j=unescape(encodeURI(s))+'',a=j.length;s=(--a/4+2)|15;words[--s]=a*8;for(;~a;){words[a>>2]|=j.charCodeAt(a)<<8*a--}for(i=j=0;i<s;i+=16){a=h;for(;j<64;a=[d=a[3],(b+((d=a[0]+[b&c|~b&d,d&b|~d&c,b^c^d,c^(b|~d)][a=j>>4]+k[j]+~~words[i|[j,5*j+1,3*j+5,7*j][a]&15])<<(a=[7,12,17,22,5,9,14,20,4,11,16,23,6,10,15,21][4*a+j++%4])|d>>>-a)),b,c]){b=a[1]|0;c=a[2]}for(j=4;j;)h[--j]+=a[j]}for(s='';j<32;){s+=((h[j>>3]>>((1^j++)*4))&15).toString(16)}return s}
function md5 (data, encoding, options) { return 'md5 not implemented' }
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

let string = "this is a secure string";
print("string:", string);
print("md5Hex(string):", md5Hex(string));
print("md5Hex(null):", md5Hex(null));
print("md5(string, 'hex'):", md5(string, "hex"));
print("md5(null, 'hex'):", md5(null, "hex"));
print("md5(string, 'binary'):", md5(string, "binary"));
print("md5(null, 'binary'):", md5(null, "binary"));
print("md5(string, 'base64'):", md5(string, "base64"));
print("md5(null, 'base64'):", md5(null, "base64"));
print("md5(string, 'base64url'):", md5(string, "base64url"));
print("md5(null, 'base64url'):", md5(null, "base64url"));
print("sha256Hex(string):", sha256Hex(string));
print("sha256Hex(null):", sha256Hex(null));
print("sha256(string, 'hex'):", sha256(string, "hex"));
print("sha256(null, 'hex'):", sha256(null, "hex"));
print("sha256(string, 'binary'):", sha256(string, "binary"));
print("sha256(null, 'binary'):", sha256(null, "binary"));
print("sha256(string, 'base64'):", sha256(string, "base64"));
print("sha256(null, 'base64'):", sha256(null, "base64"));
print("sha256(string, 'base64url'):", sha256(string, "base64url"));
print("sha256(null, 'base64url'):", sha256(null, "base64url"));
let data = ["1", "string", "more", "keys"];
print("data:", data);
print("sha256HmacChainHex(data):", sha256HmacChainHex(data));
print("sha256HmacChain(data, 'hex'):", sha256HmacChain(data, "hex"));
print("sha256HmacChain(data, 'base64'):", sha256HmacChain(data, "base64"));
print("sha256HmacChain(data, 'binary'):", sha256HmacChain(data, "binary"));
print("sha256HmacChain(data, 'base64url'):", sha256HmacChain(data, "base64url"));
