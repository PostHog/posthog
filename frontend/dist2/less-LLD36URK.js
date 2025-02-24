import{b as N,e as b,g as u,j as m}from"/static/chunk-SJXEOBQC.js";var A=N((z,h)=>{b();m();u();var D=e=>({IMPORTANT:{className:"meta",begin:"!important"},HEXCOLOR:{className:"number",begin:"#([a-fA-F0-9]{6}|[a-fA-F0-9]{3})"},ATTRIBUTE_SELECTOR_MODE:{className:"selector-attr",begin:/\[/,end:/\]/,illegal:"$",contains:[e.APOS_STRING_MODE,e.QUOTE_STRING_MODE]}}),S=["a","abbr","address","article","aside","audio","b","blockquote","body","button","canvas","caption","cite","code","dd","del","details","dfn","div","dl","dt","em","fieldset","figcaption","figure","footer","form","h1","h2","h3","h4","h5","h6","header","hgroup","html","i","iframe","img","input","ins","kbd","label","legend","li","main","mark","menu","nav","object","ol","p","q","quote","samp","section","span","strong","summary","sup","table","tbody","td","textarea","tfoot","th","thead","time","tr","ul","var","video"],R=["any-hover","any-pointer","aspect-ratio","color","color-gamut","color-index","device-aspect-ratio","device-height","device-width","display-mode","forced-colors","grid","height","hover","inverted-colors","monochrome","orientation","overflow-block","overflow-inline","pointer","prefers-color-scheme","prefers-contrast","prefers-reduced-motion","prefers-reduced-transparency","resolution","scan","scripting","update","width","min-width","max-width","min-height","max-height"],f=["active","any-link","blank","checked","current","default","defined","dir","disabled","drop","empty","enabled","first","first-child","first-of-type","fullscreen","future","focus","focus-visible","focus-within","has","host","host-context","hover","indeterminate","in-range","invalid","is","lang","last-child","last-of-type","left","link","local-link","not","nth-child","nth-col","nth-last-child","nth-last-col","nth-last-of-type","nth-of-type","only-child","only-of-type","optional","out-of-range","past","placeholder-shown","read-only","read-write","required","right","root","scope","target","target-within","user-invalid","valid","visited","where"],p=["after","backdrop","before","cue","cue-region","first-letter","first-line","grammar-error","marker","part","placeholder","selection","slotted","spelling-error"],C=["align-content","align-items","align-self","animation","animation-delay","animation-direction","animation-duration","animation-fill-mode","animation-iteration-count","animation-name","animation-play-state","animation-timing-function","auto","backface-visibility","background","background-attachment","background-clip","background-color","background-image","background-origin","background-position","background-repeat","background-size","border","border-bottom","border-bottom-color","border-bottom-left-radius","border-bottom-right-radius","border-bottom-style","border-bottom-width","border-collapse","border-color","border-image","border-image-outset","border-image-repeat","border-image-slice","border-image-source","border-image-width","border-left","border-left-color","border-left-style","border-left-width","border-radius","border-right","border-right-color","border-right-style","border-right-width","border-spacing","border-style","border-top","border-top-color","border-top-left-radius","border-top-right-radius","border-top-style","border-top-width","border-width","bottom","box-decoration-break","box-shadow","box-sizing","break-after","break-before","break-inside","caption-side","clear","clip","clip-path","color","column-count","column-fill","column-gap","column-rule","column-rule-color","column-rule-style","column-rule-width","column-span","column-width","columns","content","counter-increment","counter-reset","cursor","direction","display","empty-cells","filter","flex","flex-basis","flex-direction","flex-flow","flex-grow","flex-shrink","flex-wrap","float","font","font-display","font-family","font-feature-settings","font-kerning","font-language-override","font-size","font-size-adjust","font-smoothing","font-stretch","font-style","font-variant","font-variant-ligatures","font-variation-settings","font-weight","height","hyphens","icon","image-orientation","image-rendering","image-resolution","ime-mode","inherit","initial","justify-content","left","letter-spacing","line-height","list-style","list-style-image","list-style-position","list-style-type","margin","margin-bottom","margin-left","margin-right","margin-top","marks","mask","max-height","max-width","min-height","min-width","nav-down","nav-index","nav-left","nav-right","nav-up","none","normal","object-fit","object-position","opacity","order","orphans","outline","outline-color","outline-offset","outline-style","outline-width","overflow","overflow-wrap","overflow-x","overflow-y","padding","padding-bottom","padding-left","padding-right","padding-top","page-break-after","page-break-before","page-break-inside","perspective","perspective-origin","pointer-events","position","quotes","resize","right","src","tab-size","table-layout","text-align","text-align-last","text-decoration","text-decoration-color","text-decoration-line","text-decoration-style","text-indent","text-overflow","text-rendering","text-shadow","text-transform","text-underline-position","top","transform","transform-origin","transform-style","transition","transition-delay","transition-duration","transition-property","transition-timing-function","unicode-bidi","vertical-align","visibility","white-space","widows","width","word-break","word-spacing","word-wrap","z-index"].reverse(),L=f.concat(p);function I(e){let a=D(e),E=L,v="and or not only",t="[\\w-]+",i="("+t+"|@\\{"+t+"\\})",s=[],n=[],l=function(r){return{className:"string",begin:"~?"+r+".*?"+r}},o=function(r,k,x){return{className:r,begin:k,relevance:x}},c={$pattern:/[a-z-]+/,keyword:v,attribute:R.join(" ")},y={begin:"\\(",end:"\\)",contains:n,keywords:c,relevance:0};n.push(e.C_LINE_COMMENT_MODE,e.C_BLOCK_COMMENT_MODE,l("'"),l('"'),e.CSS_NUMBER_MODE,{begin:"(url|data-uri)\\(",starts:{className:"string",end:"[\\)\\n]",excludeEnd:!0}},a.HEXCOLOR,y,o("variable","@@?"+t,10),o("variable","@\\{"+t+"\\}"),o("built_in","~?`[^`]*?`"),{className:"attribute",begin:t+"\\s*:",end:":",returnBegin:!0,excludeEnd:!0},a.IMPORTANT);let d=n.concat({begin:/\{/,end:/\}/,contains:s}),_={beginKeywords:"when",endsWithParent:!0,contains:[{beginKeywords:"and not"}].concat(n)},w={begin:i+"\\s*:",returnBegin:!0,end:/[;}]/,relevance:0,contains:[{begin:/-(webkit|moz|ms|o)-/},{className:"attribute",begin:"\\b("+C.join("|")+")\\b",end:/(?=:)/,starts:{endsWithParent:!0,illegal:"[<=$]",relevance:0,contains:n}}]},O={className:"keyword",begin:"@(import|media|charset|font-face|(-[a-z]+-)?keyframes|supports|document|namespace|page|viewport|host)\\b",starts:{end:"[;{}]",keywords:c,returnEnd:!0,contains:n,relevance:0}},M={className:"variable",variants:[{begin:"@"+t+"\\s*:",relevance:15},{begin:"@"+t}],starts:{end:"[;}]",returnEnd:!0,contains:d}},g={variants:[{begin:"[\\.#:&\\[>]",end:"[;{}]"},{begin:i,end:/\{/}],returnBegin:!0,returnEnd:!0,illegal:`[<='$"]`,relevance:0,contains:[e.C_LINE_COMMENT_MODE,e.C_BLOCK_COMMENT_MODE,_,o("keyword","all\\b"),o("variable","@\\{"+t+"\\}"),{begin:"\\b("+S.join("|")+")\\b",className:"selector-tag"},o("selector-tag",i+"%?",0),o("selector-id","#"+i),o("selector-class","\\."+i,0),o("selector-tag","&",0),a.ATTRIBUTE_SELECTOR_MODE,{className:"selector-pseudo",begin:":("+f.join("|")+")"},{className:"selector-pseudo",begin:"::("+p.join("|")+")"},{begin:"\\(",end:"\\)",contains:d},{begin:"!important"}]},T={begin:t+`:(:)?(${E.join("|")})`,returnBegin:!0,contains:[g]};return s.push(e.C_LINE_COMMENT_MODE,e.C_BLOCK_COMMENT_MODE,O,M,T,w,g),{name:"Less",case_insensitive:!0,illegal:`[=>'/<($"]`,contains:s}}h.exports=I});export default A();
//# sourceMappingURL=/static/less-LLD36URK.js.map
