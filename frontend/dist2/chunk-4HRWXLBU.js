import{b as r,e as n,g as i,j as s}from"/static/chunk-SJXEOBQC.js";var a=r((d,o)=>{n();s();i();o.exports=t;t.displayName="jolie";t.aliases=[];function t(e){e.languages.jolie=e.languages.extend("clike",{string:{pattern:/(^|[^\\])"(?:\\[\s\S]|[^"\\])*"/,lookbehind:!0,greedy:!0},"class-name":{pattern:/((?:\b(?:as|courier|embed|in|inputPort|outputPort|service)\b|@)[ \t]*)\w+/,lookbehind:!0},keyword:/\b(?:as|cH|comp|concurrent|constants|courier|cset|csets|default|define|else|embed|embedded|execution|exit|extender|for|foreach|forward|from|global|if|import|in|include|init|inputPort|install|instanceof|interface|is_defined|linkIn|linkOut|main|new|nullProcess|outputPort|over|private|provide|public|scope|sequential|service|single|spawn|synchronized|this|throw|throws|type|undef|until|while|with)\b/,function:/\b[a-z_]\w*(?=[ \t]*[@(])/i,number:/(?:\b\d+(?:\.\d*)?|\B\.\d+)(?:e[+-]?\d+)?l?/i,operator:/-[-=>]?|\+[+=]?|<[<=]?|[>=*!]=?|&&|\|\||[?\/%^@|]/,punctuation:/[()[\]{},;.:]/,builtin:/\b(?:Byte|any|bool|char|double|enum|float|int|length|long|ranges|regex|string|undefined|void)\b/}),e.languages.insertBefore("jolie","keyword",{aggregates:{pattern:/(\bAggregates\s*:\s*)(?:\w+(?:\s+with\s+\w+)?\s*,\s*)*\w+(?:\s+with\s+\w+)?/,lookbehind:!0,inside:{keyword:/\bwith\b/,"class-name":/\w+/,punctuation:/,/}},redirects:{pattern:/(\bRedirects\s*:\s*)(?:\w+\s*=>\s*\w+\s*,\s*)*(?:\w+\s*=>\s*\w+)/,lookbehind:!0,inside:{punctuation:/,/,"class-name":/\w+/,operator:/=>/}},property:{pattern:/\b(?:Aggregates|[Ii]nterfaces|Java|Javascript|Jolie|[Ll]ocation|OneWay|[Pp]rotocol|Redirects|RequestResponse)\b(?=[ \t]*:)/}})}});export{a};
//# sourceMappingURL=/static/chunk-4HRWXLBU.js.map
