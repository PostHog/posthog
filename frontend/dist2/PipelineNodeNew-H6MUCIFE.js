import{c}from"/static/chunk-3GI7I3TJ.js";import{b as O}from"/static/chunk-L4XWFANL.js";import"/static/chunk-BZKARP3H.js";import"/static/chunk-OENI2BLK.js";import{a as x,b as B,c as v}from"/static/chunk-FXGTI5H5.js";import{b as k}from"/static/chunk-42RP32RK.js";import"/static/chunk-6RK4TW7P.js";import"/static/chunk-PGNZR35W.js";import{a as g,c as F}from"/static/chunk-4ZWY3YW2.js";import"/static/chunk-ONCHN4RU.js";import"/static/chunk-X4GKH4OI.js";import"/static/chunk-QWUPOSXD.js";import"/static/chunk-NDVJEFKZ.js";import"/static/chunk-DT27PZCF.js";import"/static/chunk-67FTXEWX.js";import"/static/chunk-QUCOEN55.js";import"/static/chunk-G6Q3YRDS.js";import"/static/chunk-OFFTP67N.js";import"/static/chunk-WTEAZEML.js";import"/static/chunk-TBYU2GKH.js";import"/static/chunk-DJ5KSU5H.js";import"/static/chunk-MOVKLCV5.js";import"/static/chunk-FT4MFWRB.js";import"/static/chunk-YDKHEMDP.js";import"/static/chunk-7SO55T25.js";import"/static/chunk-HRNZBUVG.js";import"/static/chunk-KBNOIM2W.js";import"/static/chunk-BB32DDTD.js";import"/static/chunk-QB3AUFV2.js";import"/static/chunk-PWG7LMNW.js";import"/static/chunk-CEZSENEJ.js";import"/static/chunk-GOBPXP3Z.js";import{Bi as d,Do as P,Gm as u,Pg as h,Sd as y,Sm as L,Tc as b,Tm as w,a as J,f as X,gn as D,m as A,r as I,ze as _}from"/static/chunk-TW5IU73S.js";import"/static/chunk-XPJ4MQJV.js";import"/static/chunk-KQJ3FYBQ.js";import{F as T,a as R}from"/static/chunk-3UDJFOQH.js";import"/static/chunk-HHT4SG7V.js";import"/static/chunk-K7LQKAJG.js";import"/static/chunk-QQTK3LZH.js";import"/static/chunk-IJQNM355.js";import"/static/chunk-4CN6THWS.js";import"/static/chunk-272RTCFX.js";import"/static/chunk-2ROB4QWU.js";import"/static/chunk-ALT2ZZSO.js";import"/static/chunk-UE6SLBBN.js";import"/static/chunk-GINZUAUY.js";import"/static/chunk-SQELCOUW.js";import"/static/chunk-IGYUTZ65.js";import"/static/chunk-YM6UBNGD.js";import"/static/chunk-C6TQ5FFZ.js";import"/static/chunk-GXGA523B.js";import"/static/chunk-N4MMWRNK.js";import"/static/chunk-NRLAI7OY.js";import"/static/chunk-LVVHNICT.js";import"/static/chunk-2AXSSSSX.js";import"/static/chunk-DGXQI7RB.js";import"/static/chunk-HUCRWDLX.js";import"/static/chunk-RFEQG3YN.js";import"/static/chunk-PUISI233.js";import{d as m,e as E,g as N,j as S}from"/static/chunk-SJXEOBQC.js";E();S();N();var s=m(J()),f=m(X());var C=m(R());var e=m(I()),G=({params:{stage:n,id:i}})=>{let t=i&&/^\d+$/.test(i)?parseInt(i):void 0,p=t&&!isNaN(t)?t:null,o=p?null:i?.startsWith("hog-")?i.slice(4):null,a=o?null:i??null;return{stage:v[n+"s"]||null,pluginId:p,batchExportDestination:a,hogFunctionId:o}},Te={component:M,logic:g,paramsToProps:G};function j(n){return{backend:"plugin",id:n.id,name:n.name,description:n.description||"",icon:(0,e.jsx)(D,{plugin:n}),url:n.url}}function M(n={}){let{featureFlags:i}=(0,s.useValues)(A),{stage:t,pluginId:p,batchExportDestination:o,hogFunctionId:a}=G({params:n});if(!t)return(0,e.jsx)(u,{object:"pipeline app stage"});if(p){let l=(0,e.jsx)(B,{stage:t,pluginId:p});return t==="destination"?(0,e.jsx)(d,{feature:"data_pipelines",children:l}):l}return o?t!=="destination"?(0,e.jsx)(u,{object:o}):(0,e.jsx)(d,{feature:"data_pipelines",children:(0,e.jsx)(x,{service:o})}):a?(0,e.jsx)(F,{templateId:a}):t==="transformation"?(0,e.jsx)(c,{types:["transformation"]}):t==="destination"?(0,e.jsx)(c,{types:L}):t==="site-app"?i[T.SITE_APP_FUNCTIONS]?(0,e.jsx)(c,{types:w}):(0,e.jsx)(U,{}):t==="source"?(0,e.jsx)(O,{}):(0,e.jsx)(u,{object:"pipeline new options"})}function U(){let{plugins:n,loading:i}=(0,s.useValues)(k),t=Object.values(n).map(j);return(0,e.jsx)($,{stage:"site-app",targets:t,loading:i})}function $({stage:n,targets:i,loading:t}){let{hashParams:p}=(0,s.useValues)(f.router),{loadPlugins:o}=(0,s.useActions)(g);return(0,C.useEffect)(()=>{o()},[]),(0,e.jsx)(e.Fragment,{children:(0,e.jsx)(_,{dataSource:i,size:"small",loading:t,columns:[{title:"App",width:0,render:function(l,r){return r.icon}},{title:"Name",sticky:!0,render:function(l,r){return(0,e.jsx)(h,{to:P.pipelineNodeNew(n,r.id),title:r.name,description:r.description})}},{title:"Actions",width:100,align:"right",render:function(l,r){return(0,e.jsx)(y,{type:"primary","data-attr":`new-${n}-${r.id}`,icon:(0,e.jsx)(b,{}),to:(0,f.combineUrl)(P.pipelineNodeNew(n,r.id),{},p).url,children:"Create"})}}]})})}export{M as PipelineNodeNew,Te as scene};
//# sourceMappingURL=/static/PipelineNodeNew-H6MUCIFE.js.map
