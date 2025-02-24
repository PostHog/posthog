import{b as re,e as P,g as C,j as H}from"/static/chunk-SJXEOBQC.js";var We=re((vn,ze)=>{"use strict";P();H();C();function ye(e){return e instanceof Map?e.clear=e.delete=e.set=function(){throw new Error("map is read-only")}:e instanceof Set&&(e.add=e.clear=e.delete=function(){throw new Error("set is read-only")}),Object.freeze(e),Object.getOwnPropertyNames(e).forEach(function(t){var n=e[t];typeof n=="object"&&!Object.isFrozen(n)&&ye(n)}),e}var He=ye,bt=ye;He.default=bt;var se=class{constructor(t){t.data===void 0&&(t.data={}),this.data=t.data,this.isMatchIgnored=!1}ignoreMatch(){this.isMatchIgnored=!0}};function W(e){return e.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;").replace(/'/g,"&#x27;")}function U(e,...t){let n=Object.create(null);for(let s in e)n[s]=e[s];return t.forEach(function(s){for(let g in s)n[g]=s[g]}),n}var xt="</span>",Ie=e=>!!e.kind,Ee=class{constructor(t,n){this.buffer="",this.classPrefix=n.classPrefix,t.walk(this)}addText(t){this.buffer+=W(t)}openNode(t){if(!Ie(t))return;let n=t.kind;t.sublanguage||(n=`${this.classPrefix}${n}`),this.span(n)}closeNode(t){Ie(t)&&(this.buffer+=xt)}value(){return this.buffer}span(t){this.buffer+=`<span class="${t}">`}},be=class e{constructor(){this.rootNode={children:[]},this.stack=[this.rootNode]}get top(){return this.stack[this.stack.length-1]}get root(){return this.rootNode}add(t){this.top.children.push(t)}openNode(t){let n={kind:t,children:[]};this.add(n),this.stack.push(n)}closeNode(){if(this.stack.length>1)return this.stack.pop()}closeAllNodes(){for(;this.closeNode(););}toJSON(){return JSON.stringify(this.rootNode,null,4)}walk(t){return this.constructor._walk(t,this.rootNode)}static _walk(t,n){return typeof n=="string"?t.addText(n):n.children&&(t.openNode(n),n.children.forEach(s=>this._walk(t,s)),t.closeNode(n)),t}static _collapse(t){typeof t!="string"&&t.children&&(t.children.every(n=>typeof n=="string")?t.children=[t.children.join("")]:t.children.forEach(n=>{e._collapse(n)}))}},xe=class extends be{constructor(t){super(),this.options=t}addKeyword(t,n){t!==""&&(this.openNode(n),this.addText(t),this.closeNode())}addText(t){t!==""&&this.add(t)}addSublanguage(t,n){let s=t.root;s.kind=n,s.sublanguage=!0,this.add(s)}toHTML(){return new Ee(this,this.options).value()}finalize(){return!0}};function _t(e){return new RegExp(e.replace(/[-/\\^$*+?.()|[\]{}]/g,"\\$&"),"m")}function X(e){return e?typeof e=="string"?e:e.source:null}function vt(...e){return e.map(n=>X(n)).join("")}function Nt(...e){return"("+e.map(n=>X(n)).join("|")+")"}function Rt(e){return new RegExp(e.toString()+"|").exec("").length-1}function yt(e,t){let n=e&&e.exec(t);return n&&n.index===0}var wt=/\[(?:[^\\\]]|\\.)*\]|\(\??|\\([1-9][0-9]*)|\\./;function Mt(e,t="|"){let n=0;return e.map(s=>{n+=1;let g=n,h=X(s),b="";for(;h.length>0;){let i=wt.exec(h);if(!i){b+=h;break}b+=h.substring(0,i.index),h=h.substring(i.index+i[0].length),i[0][0]==="\\"&&i[1]?b+="\\"+String(Number(i[1])+g):(b+=i[0],i[0]==="("&&n++)}return b}).map(s=>`(${s})`).join(t)}var mt=/\b\B/,Ue="[a-zA-Z]\\w*",we="[a-zA-Z_]\\w*",Me="\\b\\d+(\\.\\d+)?",je="(-?)(\\b0[xX][a-fA-F0-9]+|(\\b\\d+(\\.\\d*)?|\\.\\d+)([eE][-+]?\\d+)?)",$e="\\b(0b[01]+)",Ot="!|!=|!==|%|%=|&|&&|&=|\\*|\\*=|\\+|\\+=|,|-|-=|/=|/|:|;|<<|<<=|<=|<|===|==|=|>>>=|>>=|>=|>>>|>>|>|\\?|\\[|\\{|\\(|\\^|\\^=|\\||\\|=|\\|\\||~",kt=(e={})=>{let t=/^#![ ]*\//;return e.binary&&(e.begin=vt(t,/.*\b/,e.binary,/\b.*/)),U({className:"meta",begin:t,end:/$/,relevance:0,"on:begin":(n,s)=>{n.index!==0&&s.ignoreMatch()}},e)},Y={begin:"\\\\[\\s\\S]",relevance:0},At={className:"string",begin:"'",end:"'",illegal:"\\n",contains:[Y]},St={className:"string",begin:'"',end:'"',illegal:"\\n",contains:[Y]},Ge={begin:/\b(a|an|the|are|I'm|isn't|don't|doesn't|won't|but|just|should|pretty|simply|enough|gonna|going|wtf|so|such|will|you|your|they|like|more)\b/},ae=function(e,t,n={}){let s=U({className:"comment",begin:e,end:t,contains:[]},n);return s.contains.push(Ge),s.contains.push({className:"doctag",begin:"(?:TODO|FIXME|NOTE|BUG|OPTIMIZE|HACK|XXX):",relevance:0}),s},Lt=ae("//","$"),It=ae("/\\*","\\*/"),Bt=ae("#","$"),Tt={className:"number",begin:Me,relevance:0},Dt={className:"number",begin:je,relevance:0},Pt={className:"number",begin:$e,relevance:0},Ct={className:"number",begin:Me+"(%|em|ex|ch|rem|vw|vh|vmin|vmax|cm|mm|in|pt|pc|px|deg|grad|rad|turn|s|ms|Hz|kHz|dpi|dpcm|dppx)?",relevance:0},Ht={begin:/(?=\/[^/\n]*\/)/,contains:[{className:"regexp",begin:/\//,end:/\/[gimuy]*/,illegal:/\n/,contains:[Y,{begin:/\[/,end:/\]/,relevance:0,contains:[Y]}]}]},Ut={className:"title",begin:Ue,relevance:0},jt={className:"title",begin:we,relevance:0},$t={begin:"\\.\\s*"+we,relevance:0},Gt=function(e){return Object.assign(e,{"on:begin":(t,n)=>{n.data._beginMatch=t[1]},"on:end":(t,n)=>{n.data._beginMatch!==t[1]&&n.ignoreMatch()}})},ie=Object.freeze({__proto__:null,MATCH_NOTHING_RE:mt,IDENT_RE:Ue,UNDERSCORE_IDENT_RE:we,NUMBER_RE:Me,C_NUMBER_RE:je,BINARY_NUMBER_RE:$e,RE_STARTERS_RE:Ot,SHEBANG:kt,BACKSLASH_ESCAPE:Y,APOS_STRING_MODE:At,QUOTE_STRING_MODE:St,PHRASAL_WORDS_MODE:Ge,COMMENT:ae,C_LINE_COMMENT_MODE:Lt,C_BLOCK_COMMENT_MODE:It,HASH_COMMENT_MODE:Bt,NUMBER_MODE:Tt,C_NUMBER_MODE:Dt,BINARY_NUMBER_MODE:Pt,CSS_NUMBER_MODE:Ct,REGEXP_MODE:Ht,TITLE_MODE:Ut,UNDERSCORE_TITLE_MODE:jt,METHOD_GUARD:$t,END_SAME_AS_BEGIN:Gt});function Kt(e,t){e.input[e.index-1]==="."&&t.ignoreMatch()}function Ft(e,t){t&&e.beginKeywords&&(e.begin="\\b("+e.beginKeywords.split(" ").join("|")+")(?!\\.)(?=\\b|\\s)",e.__beforeBegin=Kt,e.keywords=e.keywords||e.beginKeywords,delete e.beginKeywords,e.relevance===void 0&&(e.relevance=0))}function zt(e,t){Array.isArray(e.illegal)&&(e.illegal=Nt(...e.illegal))}function Wt(e,t){if(e.match){if(e.begin||e.end)throw new Error("begin & end are not supported with match");e.begin=e.match,delete e.match}}function Vt(e,t){e.relevance===void 0&&(e.relevance=1)}var qt=["of","and","for","in","not","or","if","then","parent","list","value"],Xt="keyword";function Ke(e,t,n=Xt){let s={};return typeof e=="string"?g(n,e.split(" ")):Array.isArray(e)?g(n,e):Object.keys(e).forEach(function(h){Object.assign(s,Ke(e[h],t,h))}),s;function g(h,b){t&&(b=b.map(i=>i.toLowerCase())),b.forEach(function(i){let a=i.split("|");s[a[0]]=[h,Yt(a[0],a[1])]})}}function Yt(e,t){return t?Number(t):Jt(e)?0:1}function Jt(e){return qt.includes(e.toLowerCase())}function Zt(e,{plugins:t}){function n(i,a){return new RegExp(X(i),"m"+(e.case_insensitive?"i":"")+(a?"g":""))}class s{constructor(){this.matchIndexes={},this.regexes=[],this.matchAt=1,this.position=0}addRule(a,l){l.position=this.position++,this.matchIndexes[this.matchAt]=l,this.regexes.push([l,a]),this.matchAt+=Rt(a)+1}compile(){this.regexes.length===0&&(this.exec=()=>null);let a=this.regexes.map(l=>l[1]);this.matcherRe=n(Mt(a),!0),this.lastIndex=0}exec(a){this.matcherRe.lastIndex=this.lastIndex;let l=this.matcherRe.exec(a);if(!l)return null;let u=l.findIndex((w,G)=>G>0&&w!==void 0),_=this.matchIndexes[u];return l.splice(0,u),Object.assign(l,_)}}class g{constructor(){this.rules=[],this.multiRegexes=[],this.count=0,this.lastIndex=0,this.regexIndex=0}getMatcher(a){if(this.multiRegexes[a])return this.multiRegexes[a];let l=new s;return this.rules.slice(a).forEach(([u,_])=>l.addRule(u,_)),l.compile(),this.multiRegexes[a]=l,l}resumingScanAtSamePosition(){return this.regexIndex!==0}considerAll(){this.regexIndex=0}addRule(a,l){this.rules.push([a,l]),l.type==="begin"&&this.count++}exec(a){let l=this.getMatcher(this.regexIndex);l.lastIndex=this.lastIndex;let u=l.exec(a);if(this.resumingScanAtSamePosition()&&!(u&&u.index===this.lastIndex)){let _=this.getMatcher(0);_.lastIndex=this.lastIndex+1,u=_.exec(a)}return u&&(this.regexIndex+=u.position+1,this.regexIndex===this.count&&this.considerAll()),u}}function h(i){let a=new g;return i.contains.forEach(l=>a.addRule(l.begin,{rule:l,type:"begin"})),i.terminatorEnd&&a.addRule(i.terminatorEnd,{type:"end"}),i.illegal&&a.addRule(i.illegal,{type:"illegal"}),a}function b(i,a){let l=i;if(i.isCompiled)return l;[Wt].forEach(_=>_(i,a)),e.compilerExtensions.forEach(_=>_(i,a)),i.__beforeBegin=null,[Ft,zt,Vt].forEach(_=>_(i,a)),i.isCompiled=!0;let u=null;if(typeof i.keywords=="object"&&(u=i.keywords.$pattern,delete i.keywords.$pattern),i.keywords&&(i.keywords=Ke(i.keywords,e.case_insensitive)),i.lexemes&&u)throw new Error("ERR: Prefer `keywords.$pattern` to `mode.lexemes`, BOTH are not allowed. (see mode reference) ");return u=u||i.lexemes||/\w+/,l.keywordPatternRe=n(u,!0),a&&(i.begin||(i.begin=/\B|\b/),l.beginRe=n(i.begin),i.endSameAsBegin&&(i.end=i.begin),!i.end&&!i.endsWithParent&&(i.end=/\B|\b/),i.end&&(l.endRe=n(i.end)),l.terminatorEnd=X(i.end)||"",i.endsWithParent&&a.terminatorEnd&&(l.terminatorEnd+=(i.end?"|":"")+a.terminatorEnd)),i.illegal&&(l.illegalRe=n(i.illegal)),i.contains||(i.contains=[]),i.contains=[].concat(...i.contains.map(function(_){return Qt(_==="self"?i:_)})),i.contains.forEach(function(_){b(_,l)}),i.starts&&b(i.starts,a),l.matcher=h(l),l}if(e.compilerExtensions||(e.compilerExtensions=[]),e.contains&&e.contains.includes("self"))throw new Error("ERR: contains `self` is not supported at the top-level of a language.  See documentation.");return e.classNameAliases=U(e.classNameAliases||{}),b(e)}function Fe(e){return e?e.endsWithParent||Fe(e.starts):!1}function Qt(e){return e.variants&&!e.cachedVariants&&(e.cachedVariants=e.variants.map(function(t){return U(e,{variants:null},t)})),e.cachedVariants?e.cachedVariants:Fe(e)?U(e,{starts:e.starts?U(e.starts):null}):Object.isFrozen(e)?U(e):e}var en="10.7.3";function tn(e){return!!(e||e==="")}function nn(e){let t={props:["language","code","autodetect"],data:function(){return{detectedLanguage:"",unknownLanguage:!1}},computed:{className(){return this.unknownLanguage?"":"hljs "+this.detectedLanguage},highlighted(){if(!this.autoDetect&&!e.getLanguage(this.language))return console.warn(`The language "${this.language}" you specified could not be found.`),this.unknownLanguage=!0,W(this.code);let s={};return this.autoDetect?(s=e.highlightAuto(this.code),this.detectedLanguage=s.language):(s=e.highlight(this.language,this.code,this.ignoreIllegals),this.detectedLanguage=this.language),s.value},autoDetect(){return!this.language||tn(this.autodetect)},ignoreIllegals(){return!0}},render(s){return s("pre",{},[s("code",{class:this.className,domProps:{innerHTML:this.highlighted}})])}};return{Component:t,VuePlugin:{install(s){s.component("highlightjs",t)}}}}var rn={"after:highlightElement":({el:e,result:t,text:n})=>{let s=Be(e);if(!s.length)return;let g=document.createElement("div");g.innerHTML=t.value,t.value=sn(s,Be(g),n)}};function _e(e){return e.nodeName.toLowerCase()}function Be(e){let t=[];return function n(s,g){for(let h=s.firstChild;h;h=h.nextSibling)h.nodeType===3?g+=h.nodeValue.length:h.nodeType===1&&(t.push({event:"start",offset:g,node:h}),g=n(h,g),_e(h).match(/br|hr|img|input/)||t.push({event:"stop",offset:g,node:h}));return g}(e,0),t}function sn(e,t,n){let s=0,g="",h=[];function b(){return!e.length||!t.length?e.length?e:t:e[0].offset!==t[0].offset?e[0].offset<t[0].offset?e:t:t[0].event==="start"?e:t}function i(u){function _(w){return" "+w.nodeName+'="'+W(w.value)+'"'}g+="<"+_e(u)+[].map.call(u.attributes,_).join("")+">"}function a(u){g+="</"+_e(u)+">"}function l(u){(u.event==="start"?i:a)(u.node)}for(;e.length||t.length;){let u=b();if(g+=W(n.substring(s,u[0].offset)),s=u[0].offset,u===e){h.reverse().forEach(a);do l(u.splice(0,1)[0]),u=b();while(u===e&&u.length&&u[0].offset===s);h.reverse().forEach(i)}else u[0].event==="start"?h.push(u[0].node):h.pop(),l(u.splice(0,1)[0])}return g+W(n.substr(s))}var Te={},de=e=>{console.error(e)},De=(e,...t)=>{console.log(`WARN: ${e}`,...t)},m=(e,t)=>{Te[`${e}/${t}`]||(console.log(`Deprecated as of ${e}. ${t}`),Te[`${e}/${t}`]=!0)},pe=W,Pe=U,Ce=Symbol("nomatch"),an=function(e){let t=Object.create(null),n=Object.create(null),s=[],g=!0,h=/(^(<[^>]+>|\t|)+|\n)/gm,b="Could not find the language '{}', did you forget to load/include a language module?",i={disableAutodetect:!0,name:"Plain text",contains:[]},a={noHighlightRe:/^(no-?highlight)$/i,languageDetectRe:/\blang(?:uage)?-([\w-]+)\b/i,classPrefix:"hljs-",tabReplace:null,useBR:!1,languages:null,__emitter:xe};function l(r){return a.noHighlightRe.test(r)}function u(r){let o=r.className+" ";o+=r.parentNode?r.parentNode.className:"";let E=a.languageDetectRe.exec(o);if(E){let v=I(E[1]);return v||(De(b.replace("{}",E[1])),De("Falling back to no-highlight mode for this block.",r)),v?E[1]:"no-highlight"}return o.split(/\s+/).find(v=>l(v)||I(v))}function _(r,o,E,v){let R="",K="";typeof o=="object"?(R=r,E=o.ignoreIllegals,K=o.language,v=void 0):(m("10.7.0","highlight(lang, code, ...args) has been deprecated."),m("10.7.0",`Please use highlight(code, options) instead.
https://github.com/highlightjs/highlight.js/issues/2277`),K=r,R=o);let k={code:R,language:K};Q("before:highlight",k);let A=k.result?k.result:w(k.language,k.code,E,v);return A.code=k.code,Q("after:highlight",A),A}function w(r,o,E,v){function R(c,f){let p=F.case_insensitive?f[0].toLowerCase():f[0];return Object.prototype.hasOwnProperty.call(c.keywords,p)&&c.keywords[p]}function K(){if(!d.keywords){y.addText(N);return}let c=0;d.keywordPatternRe.lastIndex=0;let f=d.keywordPatternRe.exec(N),p="";for(;f;){p+=N.substring(c,f.index);let x=R(d,f);if(x){let[M,ne]=x;if(y.addText(p),p="",te+=ne,M.startsWith("_"))p+=f[0];else{let Et=F.classNameAliases[M]||M;y.addKeyword(f[0],Et)}}else p+=f[0];c=d.keywordPatternRe.lastIndex,f=d.keywordPatternRe.exec(N)}p+=N.substr(c),y.addText(p)}function k(){if(N==="")return;let c=null;if(typeof d.subLanguage=="string"){if(!t[d.subLanguage]){y.addText(N);return}c=w(d.subLanguage,N,!0,Le[d.subLanguage]),Le[d.subLanguage]=c.top}else c=T(N,d.subLanguage.length?d.subLanguage:null);d.relevance>0&&(te+=c.relevance),y.addSublanguage(c.emitter,c.language)}function A(){d.subLanguage!=null?k():K(),N=""}function S(c){return c.className&&y.openNode(F.classNameAliases[c.className]||c.className),d=Object.create(c,{parent:{value:d}}),d}function D(c,f,p){let x=yt(c.endRe,p);if(x){if(c["on:end"]){let M=new se(c);c["on:end"](f,M),M.isMatchIgnored&&(x=!1)}if(x){for(;c.endsParent&&c.parent;)c=c.parent;return c}}if(c.endsWithParent)return D(c.parent,f,p)}function gt(c){return d.matcher.regexIndex===0?(N+=c[0],1):(he=!0,0)}function ft(c){let f=c[0],p=c.rule,x=new se(p),M=[p.__beforeBegin,p["on:begin"]];for(let ne of M)if(ne&&(ne(c,x),x.isMatchIgnored))return gt(f);return p&&p.endSameAsBegin&&(p.endRe=_t(f)),p.skip?N+=f:(p.excludeBegin&&(N+=f),A(),!p.returnBegin&&!p.excludeBegin&&(N=f)),S(p),p.returnBegin?0:f.length}function ht(c){let f=c[0],p=o.substr(c.index),x=D(d,c,p);if(!x)return Ce;let M=d;M.skip?N+=f:(M.returnEnd||M.excludeEnd||(N+=f),A(),M.excludeEnd&&(N=f));do d.className&&y.closeNode(),!d.skip&&!d.subLanguage&&(te+=d.relevance),d=d.parent;while(d!==x.parent);return x.starts&&(x.endSameAsBegin&&(x.starts.endRe=x.endRe),S(x.starts)),M.returnEnd?0:f.length}function dt(){let c=[];for(let f=d;f!==F;f=f.parent)f.className&&c.unshift(f.className);c.forEach(f=>y.openNode(f))}let ee={};function Se(c,f){let p=f&&f[0];if(N+=c,p==null)return A(),0;if(ee.type==="begin"&&f.type==="end"&&ee.index===f.index&&p===""){if(N+=o.slice(f.index,f.index+1),!g){let x=new Error("0 width match regex");throw x.languageName=r,x.badRule=ee.rule,x}return 1}if(ee=f,f.type==="begin")return ft(f);if(f.type==="illegal"&&!E){let x=new Error('Illegal lexeme "'+p+'" for mode "'+(d.className||"<unnamed>")+'"');throw x.mode=d,x}else if(f.type==="end"){let x=ht(f);if(x!==Ce)return x}if(f.type==="illegal"&&p==="")return 1;if(fe>1e5&&fe>f.index*3)throw new Error("potential infinite loop, way more iterations than matches");return N+=p,p.length}let F=I(r);if(!F)throw de(b.replace("{}",r)),new Error('Unknown language: "'+r+'"');let pt=Zt(F,{plugins:s}),ge="",d=v||pt,Le={},y=new a.__emitter(a);dt();let N="",te=0,z=0,fe=0,he=!1;try{for(d.matcher.considerAll();;){fe++,he?he=!1:d.matcher.considerAll(),d.matcher.lastIndex=z;let c=d.matcher.exec(o);if(!c)break;let f=o.substring(z,c.index),p=Se(f,c);z=c.index+p}return Se(o.substr(z)),y.closeAllNodes(),y.finalize(),ge=y.toHTML(),{relevance:Math.floor(te),value:ge,language:r,illegal:!1,emitter:y,top:d}}catch(c){if(c.message&&c.message.includes("Illegal"))return{illegal:!0,illegalBy:{msg:c.message,context:o.slice(z-100,z+100),mode:c.mode},sofar:ge,relevance:0,value:pe(o),emitter:y};if(g)return{illegal:!1,relevance:0,value:pe(o),emitter:y,language:r,top:d,errorRaised:c};throw c}}function G(r){let o={relevance:0,emitter:new a.__emitter(a),value:pe(r),illegal:!1,top:i};return o.emitter.addText(r),o}function T(r,o){o=o||a.languages||Object.keys(t);let E=G(r),v=o.filter(I).filter(Ae).map(S=>w(S,r,!1));v.unshift(E);let R=v.sort((S,D)=>{if(S.relevance!==D.relevance)return D.relevance-S.relevance;if(S.language&&D.language){if(I(S.language).supersetOf===D.language)return 1;if(I(D.language).supersetOf===S.language)return-1}return 0}),[K,k]=R,A=K;return A.second_best=k,A}function J(r){return a.tabReplace||a.useBR?r.replace(h,o=>o===`
`?a.useBR?"<br>":o:a.tabReplace?o.replace(/\t/g,a.tabReplace):o):r}function O(r,o,E){let v=o?n[o]:E;r.classList.add("hljs"),v&&r.classList.add(v)}let oe={"before:highlightElement":({el:r})=>{a.useBR&&(r.innerHTML=r.innerHTML.replace(/\n/g,"").replace(/<br[ /]*>/g,`
`))},"after:highlightElement":({result:r})=>{a.useBR&&(r.value=r.value.replace(/\n/g,"<br>"))}},q=/^(<[^>]+>|\t)+/gm,Qe={"after:highlightElement":({result:r})=>{a.tabReplace&&(r.value=r.value.replace(q,o=>o.replace(/\t/g,a.tabReplace)))}};function Z(r){let o=null,E=u(r);if(l(E))return;Q("before:highlightElement",{el:r,language:E}),o=r;let v=o.textContent,R=E?_(v,{language:E,ignoreIllegals:!0}):T(v);Q("after:highlightElement",{el:r,result:R,text:v}),r.innerHTML=R.value,O(r,E,R.language),r.result={language:R.language,re:R.relevance,relavance:R.relevance},R.second_best&&(r.second_best={language:R.second_best.language,re:R.second_best.relevance,relavance:R.second_best.relevance})}function et(r){r.useBR&&(m("10.3.0","'useBR' will be removed entirely in v11.0"),m("10.3.0","Please see https://github.com/highlightjs/highlight.js/issues/2559")),a=Pe(a,r)}let ce=()=>{if(ce.called)return;ce.called=!0,m("10.6.0","initHighlighting() is deprecated.  Use highlightAll() instead."),document.querySelectorAll("pre code").forEach(Z)};function tt(){m("10.6.0","initHighlightingOnLoad() is deprecated.  Use highlightAll() instead."),ue=!0}let ue=!1;function Oe(){if(document.readyState==="loading"){ue=!0;return}document.querySelectorAll("pre code").forEach(Z)}function nt(){ue&&Oe()}typeof window<"u"&&window.addEventListener&&window.addEventListener("DOMContentLoaded",nt,!1);function rt(r,o){let E=null;try{E=o(e)}catch(v){if(de("Language definition for '{}' could not be registered.".replace("{}",r)),g)de(v);else throw v;E=i}E.name||(E.name=r),t[r]=E,E.rawDefinition=o.bind(null,e),E.aliases&&ke(E.aliases,{languageName:r})}function it(r){delete t[r];for(let o of Object.keys(n))n[o]===r&&delete n[o]}function st(){return Object.keys(t)}function at(r){m("10.4.0","requireLanguage will be removed entirely in v11."),m("10.4.0","Please see https://github.com/highlightjs/highlight.js/pull/2844");let o=I(r);if(o)return o;throw new Error("The '{}' language is required, but not loaded.".replace("{}",r))}function I(r){return r=(r||"").toLowerCase(),t[r]||t[n[r]]}function ke(r,{languageName:o}){typeof r=="string"&&(r=[r]),r.forEach(E=>{n[E.toLowerCase()]=o})}function Ae(r){let o=I(r);return o&&!o.disableAutodetect}function lt(r){r["before:highlightBlock"]&&!r["before:highlightElement"]&&(r["before:highlightElement"]=o=>{r["before:highlightBlock"](Object.assign({block:o.el},o))}),r["after:highlightBlock"]&&!r["after:highlightElement"]&&(r["after:highlightElement"]=o=>{r["after:highlightBlock"](Object.assign({block:o.el},o))})}function ot(r){lt(r),s.push(r)}function Q(r,o){let E=r;s.forEach(function(v){v[E]&&v[E](o)})}function ct(r){return m("10.2.0","fixMarkup will be removed entirely in v11.0"),m("10.2.0","Please see https://github.com/highlightjs/highlight.js/issues/2534"),J(r)}function ut(r){return m("10.7.0","highlightBlock will be removed entirely in v12.0"),m("10.7.0","Please use highlightElement now."),Z(r)}Object.assign(e,{highlight:_,highlightAuto:T,highlightAll:Oe,fixMarkup:ct,highlightElement:Z,highlightBlock:ut,configure:et,initHighlighting:ce,initHighlightingOnLoad:tt,registerLanguage:rt,unregisterLanguage:it,listLanguages:st,getLanguage:I,registerAliases:ke,requireLanguage:at,autoDetection:Ae,inherit:Pe,addPlugin:ot,vuePlugin:nn(e).VuePlugin}),e.debugMode=function(){g=!1},e.safeMode=function(){g=!0},e.versionString=en;for(let r in ie)typeof ie[r]=="object"&&He(ie[r]);return Object.assign(e,ie),e.addPlugin(oe),e.addPlugin(rn),e.addPlugin(Qe),e},ln=an({});ze.exports=ln});var Ve=re((wn,me)=>{"use strict";P();H();C();(function(){var e;typeof me<"u"?e=me.exports=s:e=function(){return this||(0,eval)("this")}(),e.format=s,e.vsprintf=n,typeof console<"u"&&typeof console.log=="function"&&(e.printf=t);function t(){console.log(s.apply(null,arguments))}function n(g,h){return s.apply(null,[g].concat(h))}function s(g){for(var h=1,b=[].slice.call(arguments),i=0,a=g.length,l="",u,_=!1,w,G,T=!1,J,O=function(){return b[h++]},oe=function(){for(var q="";/\d/.test(g[i]);)q+=g[i++],u=g[i];return q.length>0?parseInt(q):null};i<a;++i)if(u=g[i],_)switch(_=!1,u=="."?(T=!1,u=g[++i]):u=="0"&&g[i+1]=="."?(T=!0,i+=2,u=g[i]):T=!0,J=oe(),u){case"b":l+=parseInt(O(),10).toString(2);break;case"c":w=O(),typeof w=="string"||w instanceof String?l+=w:l+=String.fromCharCode(parseInt(w,10));break;case"d":l+=parseInt(O(),10);break;case"f":G=String(parseFloat(O()).toFixed(J||6)),l+=T?G:G.replace(/^0/,"");break;case"j":l+=JSON.stringify(O());break;case"o":l+="0"+parseInt(O(),10).toString(8);break;case"s":l+=O();break;case"x":l+="0x"+parseInt(O(),10).toString(16);break;case"X":l+="0x"+parseInt(O(),10).toString(16).toUpperCase();break;default:l+=u;break}else u==="%"?_=!0:l+=u;return l}})()});var Xe=re((kn,qe)=>{"use strict";P();H();C();var on=Ve(),j=$(Error);qe.exports=j;j.eval=$(EvalError);j.range=$(RangeError);j.reference=$(ReferenceError);j.syntax=$(SyntaxError);j.type=$(TypeError);j.uri=$(URIError);j.create=$;function $(e){return t.displayName=e.displayName||e.name,t;function t(n){return n&&(n=on.apply(null,arguments)),new e(n)}}});var _n=re(V=>{P();H();C();var L=We(),le=Xe();V.highlight=Je;V.highlightAuto=cn;V.registerLanguage=un;V.listLanguages=gn;V.registerAlias=fn;B.prototype.addText=pn;B.prototype.addKeyword=hn;B.prototype.addSublanguage=dn;B.prototype.openNode=En;B.prototype.closeNode=bn;B.prototype.closeAllNodes=Ze;B.prototype.finalize=Ze;B.prototype.toHTML=xn;var Ye="hljs-";function Je(e,t,n){var s=L.configure({}),g=n||{},h=g.prefix,b;if(typeof e!="string")throw le("Expected `string` for name, got `%s`",e);if(!L.getLanguage(e))throw le("Unknown language: `%s` is not registered",e);if(typeof t!="string")throw le("Expected `string` for value, got `%s`",t);if(h==null&&(h=Ye),L.configure({__emitter:B,classPrefix:h}),b=L.highlight(t,{language:e,ignoreIllegals:!0}),L.configure(s||{}),b.errorRaised)throw b.errorRaised;return{relevance:b.relevance,language:b.language,value:b.emitter.rootNode.children}}function cn(e,t){var n=t||{},s=n.subset||L.listLanguages(),g=n.prefix,h=s.length,b=-1,i,a,l,u;if(g==null&&(g=Ye),typeof e!="string")throw le("Expected `string` for value, got `%s`",e);for(a={relevance:0,language:null,value:[]},i={relevance:0,language:null,value:[]};++b<h;)u=s[b],L.getLanguage(u)&&(l=Je(u,e,t),l.language=u,l.relevance>a.relevance&&(a=l),l.relevance>i.relevance&&(a=i,i=l));return a.language&&(i.secondBest=a),i}function un(e,t){L.registerLanguage(e,t)}function gn(){return L.listLanguages()}function fn(e,t){var n=e,s;t&&(n={},n[e]=t);for(s in n)L.registerAliases(n[s],{languageName:s})}function B(e){this.options=e,this.rootNode={children:[]},this.stack=[this.rootNode]}function hn(e,t){this.openNode(t),this.addText(e),this.closeNode()}function dn(e,t){var n=this.stack,s=n[n.length-1],g=e.rootNode.children,h=t?{type:"element",tagName:"span",properties:{className:[t]},children:g}:g;s.children=s.children.concat(h)}function pn(e){var t=this.stack,n,s;e!==""&&(n=t[t.length-1],s=n.children[n.children.length-1],s&&s.type==="text"?s.value+=e:n.children.push({type:"text",value:e}))}function En(e){var t=this.stack,n=this.options.classPrefix+e,s=t[t.length-1],g={type:"element",tagName:"span",properties:{className:[n]},children:[]};s.children.push(g),t.push(g)}function bn(){this.stack.pop()}function xn(){return""}function Ze(){}});export default _n();
//# sourceMappingURL=/static/core-PKJLQUNR.js.map
