import{b as R,e as f,g as v,j as h}from"/static/chunk-SJXEOBQC.js";var N=R((O,E)=>{f();h();v();E.exports=p;p.displayName="sas";p.aliases=[];function p(T){(function(o){var n=/(?:"(?:""|[^"])*"(?!")|'(?:''|[^'])*'(?!'))/.source,e=/\b(?:\d[\da-f]*x|\d+(?:\.\d+)?(?:e[+-]?\d+)?)\b/i,t={pattern:RegExp(n+"[bx]"),alias:"number"},d={pattern:/&[a-z_]\w*/i},m={pattern:/((?:^|\s|=|\())%(?:ABORT|BY|CMS|COPY|DISPLAY|DO|ELSE|END|EVAL|GLOBAL|GO|GOTO|IF|INC|INCLUDE|INDEX|INPUT|KTRIM|LENGTH|LET|LIST|LOCAL|PUT|QKTRIM|QSCAN|QSUBSTR|QSYSFUNC|QUPCASE|RETURN|RUN|SCAN|SUBSTR|SUPERQ|SYMDEL|SYMEXIST|SYMGLOBL|SYMLOCAL|SYSCALL|SYSEVALF|SYSEXEC|SYSFUNC|SYSGET|SYSRPUT|THEN|TO|TSO|UNQUOTE|UNTIL|UPCASE|WHILE|WINDOW)\b/i,lookbehind:!0,alias:"keyword"},b={pattern:/(^|\s)(?:proc\s+\w+|data(?!=)|quit|run)\b/i,alias:"keyword",lookbehind:!0},i=[/\/\*[\s\S]*?\*\//,{pattern:/(^[ \t]*|;\s*)\*[^;]*;/m,lookbehind:!0}],r={pattern:RegExp(n),greedy:!0},a=/[$%@.(){}\[\];,\\]/,l={pattern:/%?\b\w+(?=\()/,alias:"keyword"},s={function:l,"arg-value":{pattern:/(=\s*)[A-Z\.]+/i,lookbehind:!0},operator:/=/,"macro-variable":d,arg:{pattern:/[A-Z]+/i,alias:"keyword"},number:e,"numeric-constant":t,punctuation:a,string:r},g={pattern:/\b(?:format|put)\b=?[\w'$.]+/i,inside:{keyword:/^(?:format|put)(?==)/i,equals:/=/,format:{pattern:/(?:\w|\$\d)+\.\d?/,alias:"number"}}},k={pattern:/\b(?:format|put)\s+[\w']+(?:\s+[$.\w]+)+(?=;)/i,inside:{keyword:/^(?:format|put)/i,format:{pattern:/[\w$]+\.\d?/,alias:"number"}}},u={pattern:/((?:^|\s)=?)(?:catname|checkpoint execute_always|dm|endsas|filename|footnote|%include|libname|%list|lock|missing|options|page|resetline|%run|sasfile|skip|sysecho|title\d?)\b/i,lookbehind:!0,alias:"keyword"},y={pattern:/(^|\s)(?:submit(?:\s+(?:load|norun|parseonly))?|endsubmit)\b/i,lookbehind:!0,alias:"keyword"},S=/aStore|accessControl|aggregation|audio|autotune|bayesianNetClassifier|bioMedImage|boolRule|builtins|cardinality|cdm|clustering|conditionalRandomFields|configuration|copula|countreg|dataDiscovery|dataPreprocess|dataSciencePilot|dataStep|decisionTree|deduplication|deepLearn|deepNeural|deepRnn|ds2|ecm|entityRes|espCluster|explainModel|factmac|fastKnn|fcmpact|fedSql|freqTab|gVarCluster|gam|gleam|graphSemiSupLearn|hiddenMarkovModel|hyperGroup|ica|image|iml|kernalPca|langModel|ldaTopic|loadStreams|mbc|mixed|mlTools|modelPublishing|network|neuralNet|nmf|nonParametricBayes|nonlinear|optNetwork|optimization|panel|pca|percentile|phreg|pls|qkb|qlim|quantreg|recommend|regression|reinforcementLearn|robustPca|ruleMining|sampling|sandwich|sccasl|search(?:Analytics)?|sentimentAnalysis|sequence|session(?:Prop)?|severity|simSystem|simple|smartData|sparkEmbeddedProcess|sparseML|spatialreg|spc|stabilityMonitoring|svDataDescription|svm|table|text(?:Filters|Frequency|Mining|Parse|Rule(?:Develop|Score)|Topic|Util)|timeData|transpose|tsInfo|tsReconcile|uniTimeSeries|varReduce/.source,w={pattern:RegExp(/(^|\s)(?:action\s+)?(?:<act>)\.[a-z]+\b[^;]+/.source.replace(/<act>/g,function(){return S}),"i"),lookbehind:!0,inside:{keyword:RegExp(/(?:<act>)\.[a-z]+\b/.source.replace(/<act>/g,function(){return S}),"i"),action:{pattern:/(?:action)/i,alias:"keyword"},comment:i,function:l,"arg-value":s["arg-value"],operator:s.operator,argument:s.arg,number:e,"numeric-constant":t,punctuation:a,string:r}},c={pattern:/((?:^|\s)=?)(?:after|analysis|and|array|barchart|barwidth|begingraph|by|call|cas|cbarline|cfill|class(?:lev)?|close|column|computed?|contains|continue|data(?==)|define|delete|describe|document|do\s+over|do|dol|drop|dul|else|end(?:comp|source)?|entryTitle|eval(?:uate)?|exec(?:ute)?|exit|file(?:name)?|fill(?:attrs)?|flist|fnc|function(?:list)?|global|goto|group(?:by)?|headline|headskip|histogram|if|infile|keep|keylabel|keyword|label|layout|leave|legendlabel|length|libname|loadactionset|merge|midpoints|_?null_|name|noobs|nowd|ods|options|or|otherwise|out(?:put)?|over(?:lay)?|plot|print|put|raise|ranexp|rannor|rbreak|retain|return|select|session|sessref|set|source|statgraph|sum|summarize|table|temp|terminate|then\s+do|then|title\d?|to|var|when|where|xaxisopts|y2axisopts|yaxisopts)\b/i,lookbehind:!0};o.languages.sas={datalines:{pattern:/^([ \t]*)(?:cards|(?:data)?lines);[\s\S]+?^[ \t]*;/im,lookbehind:!0,alias:"string",inside:{keyword:{pattern:/^(?:cards|(?:data)?lines)/i},punctuation:/;/}},"proc-sql":{pattern:/(^proc\s+(?:fed)?sql(?:\s+[\w|=]+)?;)[\s\S]+?(?=^(?:proc\s+\w+|data|quit|run);|(?![\s\S]))/im,lookbehind:!0,inside:{sql:{pattern:RegExp(/^[ \t]*(?:select|alter\s+table|(?:create|describe|drop)\s+(?:index|table(?:\s+constraints)?|view)|create\s+unique\s+index|insert\s+into|update)(?:<str>|[^;"'])+;/.source.replace(/<str>/g,function(){return n}),"im"),alias:"language-sql",inside:o.languages.sql},"global-statements":u,"sql-statements":{pattern:/(^|\s)(?:disconnect\s+from|begin|commit|exec(?:ute)?|reset|rollback|validate)\b/i,lookbehind:!0,alias:"keyword"},number:e,"numeric-constant":t,punctuation:a,string:r}},"proc-groovy":{pattern:/(^proc\s+groovy(?:\s+[\w|=]+)?;)[\s\S]+?(?=^(?:proc\s+\w+|data|quit|run);|(?![\s\S]))/im,lookbehind:!0,inside:{comment:i,groovy:{pattern:RegExp(/(^[ \t]*submit(?:\s+(?:load|norun|parseonly))?)(?:<str>|[^"'])+?(?=endsubmit;)/.source.replace(/<str>/g,function(){return n}),"im"),lookbehind:!0,alias:"language-groovy",inside:o.languages.groovy},keyword:c,"submit-statement":y,"global-statements":u,number:e,"numeric-constant":t,punctuation:a,string:r}},"proc-lua":{pattern:/(^proc\s+lua(?:\s+[\w|=]+)?;)[\s\S]+?(?=^(?:proc\s+\w+|data|quit|run);|(?![\s\S]))/im,lookbehind:!0,inside:{comment:i,lua:{pattern:RegExp(/(^[ \t]*submit(?:\s+(?:load|norun|parseonly))?)(?:<str>|[^"'])+?(?=endsubmit;)/.source.replace(/<str>/g,function(){return n}),"im"),lookbehind:!0,alias:"language-lua",inside:o.languages.lua},keyword:c,"submit-statement":y,"global-statements":u,number:e,"numeric-constant":t,punctuation:a,string:r}},"proc-cas":{pattern:/(^proc\s+cas(?:\s+[\w|=]+)?;)[\s\S]+?(?=^(?:proc\s+\w+|quit|data);|(?![\s\S]))/im,lookbehind:!0,inside:{comment:i,"statement-var":{pattern:/((?:^|\s)=?)saveresult\s[^;]+/im,lookbehind:!0,inside:{statement:{pattern:/^saveresult\s+\S+/i,inside:{keyword:/^(?:saveresult)/i}},rest:s}},"cas-actions":w,statement:{pattern:/((?:^|\s)=?)(?:default|(?:un)?set|on|output|upload)[^;]+/im,lookbehind:!0,inside:s},step:b,keyword:c,function:l,format:g,altformat:k,"global-statements":u,number:e,"numeric-constant":t,punctuation:a,string:r}},"proc-args":{pattern:RegExp(/(^proc\s+\w+\s+)(?!\s)(?:[^;"']|<str>)+;/.source.replace(/<str>/g,function(){return n}),"im"),lookbehind:!0,inside:s},"macro-keyword":m,"macro-variable":d,"macro-string-functions":{pattern:/((?:^|\s|=))%(?:BQUOTE|NRBQUOTE|NRQUOTE|NRSTR|QUOTE|STR)\(.*?(?:[^%]\))/i,lookbehind:!0,inside:{function:{pattern:/%(?:BQUOTE|NRBQUOTE|NRQUOTE|NRSTR|QUOTE|STR)/i,alias:"keyword"},"macro-keyword":m,"macro-variable":d,"escaped-char":{pattern:/%['"()<>=¬^~;,#]/},punctuation:a}},"macro-declaration":{pattern:/^%macro[^;]+(?=;)/im,inside:{keyword:/%macro/i}},"macro-end":{pattern:/^%mend[^;]+(?=;)/im,inside:{keyword:/%mend/i}},macro:{pattern:/%_\w+(?=\()/,alias:"keyword"},input:{pattern:/\binput\s[-\w\s/*.$&]+;/i,inside:{input:{alias:"keyword",pattern:/^input/i},comment:i,number:e,"numeric-constant":t}},"options-args":{pattern:/(^options)[-'"|/\\<>*+=:()\w\s]*(?=;)/im,lookbehind:!0,inside:s},"cas-actions":w,comment:i,function:l,format:g,altformat:k,"numeric-constant":t,datetime:{pattern:RegExp(n+"(?:dt?|t)"),alias:"number"},string:r,step:b,keyword:c,"operator-keyword":{pattern:/\b(?:eq|ge|gt|in|le|lt|ne|not)\b/i,alias:"operator"},number:e,operator:/\*\*?|\|\|?|!!?|¦¦?|<[>=]?|>[<=]?|[-+\/=&]|[~¬^]=?/,punctuation:a}})(T)}});export{N as a};
//# sourceMappingURL=/static/chunk-Q3GM27HV.js.map
