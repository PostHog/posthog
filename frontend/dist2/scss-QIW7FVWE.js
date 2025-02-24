import{e,g as t,j as n}from"/static/chunk-SJXEOBQC.js";e();n();t();var a={wordPattern:/(#?-?\d*\.\d\w*%?)|([@$#!.:]?[\w-?]+%?)|[@#!.]/g,comments:{blockComment:["/*","*/"],lineComment:"//"},brackets:[["{","}"],["[","]"],["(",")"]],autoClosingPairs:[{open:"{",close:"}",notIn:["string","comment"]},{open:"[",close:"]",notIn:["string","comment"]},{open:"(",close:")",notIn:["string","comment"]},{open:'"',close:'"',notIn:["string","comment"]},{open:"'",close:"'",notIn:["string","comment"]}],surroundingPairs:[{open:"{",close:"}"},{open:"[",close:"]"},{open:"(",close:")"},{open:'"',close:'"'},{open:"'",close:"'"}],folding:{markers:{start:new RegExp("^\\s*\\/\\*\\s*#region\\b\\s*(.*?)\\s*\\*\\/"),end:new RegExp("^\\s*\\/\\*\\s*#endregion\\b.*\\*\\/")}}},l={defaultToken:"",tokenPostfix:".scss",ws:`[ 	
\r\f]*`,identifier:"-?-?([a-zA-Z]|(\\\\(([0-9a-fA-F]{1,6}\\s?)|[^[0-9a-fA-F])))([\\w\\-]|(\\\\(([0-9a-fA-F]{1,6}\\s?)|[^[0-9a-fA-F])))*",brackets:[{open:"{",close:"}",token:"delimiter.curly"},{open:"[",close:"]",token:"delimiter.bracket"},{open:"(",close:")",token:"delimiter.parenthesis"},{open:"<",close:">",token:"delimiter.angle"}],tokenizer:{root:[{include:"@selector"}],selector:[{include:"@comments"},{include:"@import"},{include:"@variabledeclaration"},{include:"@warndebug"},["[@](include)",{token:"keyword",next:"@includedeclaration"}],["[@](keyframes|-webkit-keyframes|-moz-keyframes|-o-keyframes)",{token:"keyword",next:"@keyframedeclaration"}],["[@](page|content|font-face|-moz-document)",{token:"keyword"}],["[@](charset|namespace)",{token:"keyword",next:"@declarationbody"}],["[@](function)",{token:"keyword",next:"@functiondeclaration"}],["[@](mixin)",{token:"keyword",next:"@mixindeclaration"}],["url(\\-prefix)?\\(",{token:"meta",next:"@urldeclaration"}],{include:"@controlstatement"},{include:"@selectorname"},["[&\\*]","tag"],["[>\\+,]","delimiter"],["\\[",{token:"delimiter.bracket",next:"@selectorattribute"}],["{",{token:"delimiter.curly",next:"@selectorbody"}]],selectorbody:[["[*_]?@identifier@ws:(?=(\\s|\\d|[^{;}]*[;}]))","attribute.name","@rulevalue"],{include:"@selector"},["[@](extend)",{token:"keyword",next:"@extendbody"}],["[@](return)",{token:"keyword",next:"@declarationbody"}],["}",{token:"delimiter.curly",next:"@pop"}]],selectorname:[["#{",{token:"meta",next:"@variableinterpolation"}],["(\\.|#(?=[^{])|%|(@identifier)|:)+","tag"]],selectorattribute:[{include:"@term"},["]",{token:"delimiter.bracket",next:"@pop"}]],term:[{include:"@comments"},["url(\\-prefix)?\\(",{token:"meta",next:"@urldeclaration"}],{include:"@functioninvocation"},{include:"@numbers"},{include:"@strings"},{include:"@variablereference"},["(and\\b|or\\b|not\\b)","operator"],{include:"@name"},["([<>=\\+\\-\\*\\/\\^\\|\\~,])","operator"],[",","delimiter"],["!default","literal"],["\\(",{token:"delimiter.parenthesis",next:"@parenthizedterm"}]],rulevalue:[{include:"@term"},["!important","literal"],[";","delimiter","@pop"],["{",{token:"delimiter.curly",switchTo:"@nestedproperty"}],["(?=})",{token:"",next:"@pop"}]],nestedproperty:[["[*_]?@identifier@ws:","attribute.name","@rulevalue"],{include:"@comments"},["}",{token:"delimiter.curly",next:"@pop"}]],warndebug:[["[@](warn|debug)",{token:"keyword",next:"@declarationbody"}]],import:[["[@](import)",{token:"keyword",next:"@declarationbody"}]],variabledeclaration:[["\\$@identifier@ws:","variable.decl","@declarationbody"]],urldeclaration:[{include:"@strings"},[`[^)\r
]+`,"string"],["\\)",{token:"meta",next:"@pop"}]],parenthizedterm:[{include:"@term"},["\\)",{token:"delimiter.parenthesis",next:"@pop"}]],declarationbody:[{include:"@term"},[";","delimiter","@pop"],["(?=})",{token:"",next:"@pop"}]],extendbody:[{include:"@selectorname"},["!optional","literal"],[";","delimiter","@pop"],["(?=})",{token:"",next:"@pop"}]],variablereference:[["\\$@identifier","variable.ref"],["\\.\\.\\.","operator"],["#{",{token:"meta",next:"@variableinterpolation"}]],variableinterpolation:[{include:"@variablereference"},["}",{token:"meta",next:"@pop"}]],comments:[["\\/\\*","comment","@comment"],["\\/\\/+.*","comment"]],comment:[["\\*\\/","comment","@pop"],[".","comment"]],name:[["@identifier","attribute.value"]],numbers:[["(\\d*\\.)?\\d+([eE][\\-+]?\\d+)?",{token:"number",next:"@units"}],["#[0-9a-fA-F_]+(?!\\w)","number.hex"]],units:[["(em|ex|ch|rem|fr|vmin|vmax|vw|vh|vm|cm|mm|in|px|pt|pc|deg|grad|rad|turn|s|ms|Hz|kHz|%)?","number","@pop"]],functiondeclaration:[["@identifier@ws\\(",{token:"meta",next:"@parameterdeclaration"}],["{",{token:"delimiter.curly",switchTo:"@functionbody"}]],mixindeclaration:[["@identifier@ws\\(",{token:"meta",next:"@parameterdeclaration"}],["@identifier","meta"],["{",{token:"delimiter.curly",switchTo:"@selectorbody"}]],parameterdeclaration:[["\\$@identifier@ws:","variable.decl"],["\\.\\.\\.","operator"],[",","delimiter"],{include:"@term"},["\\)",{token:"meta",next:"@pop"}]],includedeclaration:[{include:"@functioninvocation"},["@identifier","meta"],[";","delimiter","@pop"],["(?=})",{token:"",next:"@pop"}],["{",{token:"delimiter.curly",switchTo:"@selectorbody"}]],keyframedeclaration:[["@identifier","meta"],["{",{token:"delimiter.curly",switchTo:"@keyframebody"}]],keyframebody:[{include:"@term"},["{",{token:"delimiter.curly",next:"@selectorbody"}],["}",{token:"delimiter.curly",next:"@pop"}]],controlstatement:[["[@](if|else|for|while|each|media)",{token:"keyword.flow",next:"@controlstatementdeclaration"}]],controlstatementdeclaration:[["(in|from|through|if|to)\\b",{token:"keyword.flow"}],{include:"@term"},["{",{token:"delimiter.curly",switchTo:"@selectorbody"}]],functionbody:[["[@](return)",{token:"keyword"}],{include:"@variabledeclaration"},{include:"@term"},{include:"@controlstatement"},[";","delimiter"],["}",{token:"delimiter.curly",next:"@pop"}]],functioninvocation:[["@identifier\\(",{token:"meta",next:"@functionarguments"}]],functionarguments:[["\\$@identifier@ws:","attribute.name"],["[,]","delimiter"],{include:"@term"},["\\)",{token:"meta",next:"@pop"}]],strings:[['~?"',{token:"string.delimiter",next:"@stringenddoublequote"}],["~?'",{token:"string.delimiter",next:"@stringendquote"}]],stringenddoublequote:[["\\\\.","string"],['"',{token:"string.delimiter",next:"@pop"}],[".","string"]],stringendquote:[["\\\\.","string"],["'",{token:"string.delimiter",next:"@pop"}],[".","string"]]}};export{a as conf,l as language};
/*! Bundled license information:

monaco-editor/esm/vs/basic-languages/scss/scss.js:
  (*!-----------------------------------------------------------------------------
   * Copyright (c) Microsoft Corporation. All rights reserved.
   * Version: 0.49.0(383fdf3fc0e1e1a024068b8d0fd4f3dcbae74d04)
   * Released under the MIT license
   * https://github.com/microsoft/monaco-editor/blob/main/LICENSE.txt
   *-----------------------------------------------------------------------------*)
*/
//# sourceMappingURL=/static/scss-QIW7FVWE.js.map
