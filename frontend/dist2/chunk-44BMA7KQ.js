import{b as u,e as t,g as d,j as n}from"/static/chunk-SJXEOBQC.js";var c=u((E,r)=>{t();n();d();r.exports=s;s.displayName="diff";s.aliases=[];function s(l){(function(i){i.languages.diff={coord:[/^(?:\*{3}|-{3}|\+{3}).*$/m,/^@@.*@@$/m,/^\d.*$/m]};var f={"deleted-sign":"-","deleted-arrow":"<","inserted-sign":"+","inserted-arrow":">",unchanged:" ",diff:"!"};Object.keys(f).forEach(function(e){var o=f[e],a=[];/^\w+$/.test(e)||a.push(/\w+/.exec(e)[0]),e==="diff"&&a.push("bold"),i.languages.diff[e]={pattern:RegExp("^(?:["+o+`].*(?:\r
?|
|(?![\\s\\S])))+`,"m"),alias:a,inside:{line:{pattern:/(.)(?=[\s\S]).*(?:\r\n?|\n)?/,lookbehind:!0},prefix:{pattern:/[\s\S]/,alias:/\w+/.exec(e)[0]}}}}),Object.defineProperty(i.languages.diff,"PREFIXES",{value:f})})(l)}});export{c as a};
//# sourceMappingURL=/static/chunk-44BMA7KQ.js.map
