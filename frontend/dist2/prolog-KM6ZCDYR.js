import{b as C,e as a,g as o,j as t}from"/static/chunk-SJXEOBQC.js";var b=C((P,i)=>{a();t();o();function N(n){let _={begin:/[a-z][A-Za-z0-9_]*/,relevance:0},E={className:"symbol",variants:[{begin:/[A-Z][a-zA-Z0-9_]*/},{begin:/_[A-Za-z0-9_]*/}],relevance:0},c={begin:/\(/,end:/\)/,relevance:0},s={begin:/\[/,end:/\]/},g={className:"comment",begin:/%/,end:/$/,contains:[n.PHRASAL_WORDS_MODE]},A={className:"string",begin:/`/,end:/`/,contains:[n.BACKSLASH_ESCAPE]},O={className:"string",begin:/0'(\\'|.)/},r={className:"string",begin:/0'\\s/},e=[_,E,c,{begin:/:-/},s,g,n.C_BLOCK_COMMENT_MODE,n.QUOTE_STRING_MODE,n.APOS_STRING_MODE,A,O,r,n.C_NUMBER_MODE];return c.contains=e,s.contains=e,{name:"Prolog",contains:e.concat([{begin:/\.$/}])}}i.exports=N});export default b();
//# sourceMappingURL=/static/prolog-KM6ZCDYR.js.map
