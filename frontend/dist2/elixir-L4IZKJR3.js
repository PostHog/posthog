import{b as I,e as c,g as r,j as g}from"/static/chunk-SJXEOBQC.js";var N=I((R,E)=>{c();g();r();function m(n){let i="[a-zA-Z_][a-zA-Z0-9_.]*(!|\\?)?",l="[a-zA-Z_]\\w*[!?=]?|[-+~]@|<<|>>|=~|===?|<=>|[<>]=?|\\*\\*|[-/+%^&*~`|]|\\[\\]=?",a={$pattern:i,keyword:"and false then defined module in return redo retry end for true self when next until do begin unless nil break not case cond alias while ensure or include use alias fn quote require import with|0"},e={className:"subst",begin:/#\{/,end:/\}/,keywords:a},s={className:"number",begin:"(\\b0o[0-7_]+)|(\\b0b[01_]+)|(\\b0x[0-9a-fA-F_]+)|(-?\\b[1-9][0-9_]*(\\.[0-9_]+([eE][-+]?[0-9]+)?)?)",relevance:0},t=`[/|([{<"']`,S={className:"string",begin:"~[a-z](?="+t+")",contains:[{endsParent:!0,contains:[{contains:[n.BACKSLASH_ESCAPE,e],variants:[{begin:/"/,end:/"/},{begin:/'/,end:/'/},{begin:/\//,end:/\//},{begin:/\|/,end:/\|/},{begin:/\(/,end:/\)/},{begin:/\[/,end:/\]/},{begin:/\{/,end:/\}/},{begin:/</,end:/>/}]}]}]},_={className:"string",begin:"~[A-Z](?="+t+")",contains:[{begin:/"/,end:/"/},{begin:/'/,end:/'/},{begin:/\//,end:/\//},{begin:/\|/,end:/\|/},{begin:/\(/,end:/\)/},{begin:/\[/,end:/\]/},{begin:/\{/,end:/\}/},{begin:/</,end:/>/}]},b={className:"string",contains:[n.BACKSLASH_ESCAPE,e],variants:[{begin:/"""/,end:/"""/},{begin:/'''/,end:/'''/},{begin:/~S"""/,end:/"""/,contains:[]},{begin:/~S"/,end:/"/,contains:[]},{begin:/~S'''/,end:/'''/,contains:[]},{begin:/~S'/,end:/'/,contains:[]},{begin:/'/,end:/'/},{begin:/"/,end:/"/}]},d={className:"function",beginKeywords:"def defp defmacro",end:/\B\b/,contains:[n.inherit(n.TITLE_MODE,{begin:i,endsParent:!0})]},A=n.inherit(d,{className:"class",beginKeywords:"defimpl defmodule defprotocol defrecord",end:/\bdo\b|$|;/}),o=[b,_,S,n.HASH_COMMENT_MODE,A,d,{begin:"::"},{className:"symbol",begin:":(?![\\s:])",contains:[b,{begin:l}],relevance:0},{className:"symbol",begin:i+":(?!:)",relevance:0},s,{className:"variable",begin:"(\\$\\W)|((\\$|@@?)(\\w+))"},{begin:"->"},{begin:"("+n.RE_STARTERS_RE+")\\s*",contains:[n.HASH_COMMENT_MODE,{begin:/\/: (?=\d+\s*[,\]])/,relevance:0,contains:[s]},{className:"regexp",illegal:"\\n",contains:[n.BACKSLASH_ESCAPE,e],variants:[{begin:"/",end:"/[a-z]*"},{begin:"%r\\[",end:"\\][a-z]*"}]}],relevance:0}];return e.contains=o,{name:"Elixir",keywords:a,contains:o}}E.exports=m});export default N();
//# sourceMappingURL=/static/elixir-L4IZKJR3.js.map
