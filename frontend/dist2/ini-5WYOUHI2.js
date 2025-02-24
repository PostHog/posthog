import{e,g as n,j as s}from"/static/chunk-SJXEOBQC.js";e();s();n();var a={comments:{lineComment:"#"},brackets:[["{","}"],["[","]"],["(",")"]],autoClosingPairs:[{open:"{",close:"}"},{open:"[",close:"]"},{open:"(",close:")"},{open:'"',close:'"'},{open:"'",close:"'"}],surroundingPairs:[{open:"{",close:"}"},{open:"[",close:"]"},{open:"(",close:")"},{open:'"',close:'"'},{open:"'",close:"'"}]},r={defaultToken:"",tokenPostfix:".ini",escapes:/\\(?:[abfnrtv\\"']|x[0-9A-Fa-f]{1,4}|u[0-9A-Fa-f]{4}|U[0-9A-Fa-f]{8})/,tokenizer:{root:[[/^\[[^\]]*\]/,"metatag"],[/(^\w+)(\s*)(\=)/,["key","","delimiter"]],{include:"@whitespace"},[/\d+/,"number"],[/"([^"\\]|\\.)*$/,"string.invalid"],[/'([^'\\]|\\.)*$/,"string.invalid"],[/"/,"string",'@string."'],[/'/,"string","@string.'"]],whitespace:[[/[ \t\r\n]+/,""],[/^\s*[#;].*$/,"comment"]],string:[[/[^\\"']+/,"string"],[/@escapes/,"string.escape"],[/\\./,"string.escape.invalid"],[/["']/,{cases:{"$#==$S2":{token:"string",next:"@pop"},"@default":"string"}}]]}};export{a as conf,r as language};
/*! Bundled license information:

monaco-editor/esm/vs/basic-languages/ini/ini.js:
  (*!-----------------------------------------------------------------------------
   * Copyright (c) Microsoft Corporation. All rights reserved.
   * Version: 0.49.0(383fdf3fc0e1e1a024068b8d0fd4f3dcbae74d04)
   * Released under the MIT license
   * https://github.com/microsoft/monaco-editor/blob/main/LICENSE.txt
   *-----------------------------------------------------------------------------*)
*/
//# sourceMappingURL=/static/ini-5WYOUHI2.js.map
