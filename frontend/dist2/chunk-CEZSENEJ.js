import{Nd as v,Xk as C,cl as x,h as H,r as k,se as T}from"/static/chunk-TW5IU73S.js";import{a as B,ea as h,fb as u}from"/static/chunk-3UDJFOQH.js";import{d as i,e as g,g as b,j as S}from"/static/chunk-SJXEOBQC.js";g();S();b();var y=i(H());var r=i(B());var a=i(k());function G({labels:o,data:n,type:s="bar",maximumIndicator:c=!0,loading:P=!1,className:w}){let l=(0,r.useRef)(null),I=(0,r.useRef)(null),[L,E]=(0,r.useState)(!1),[D,N]=(0,r.useState)(null),d=M(n)?n:[{name:"Data",color:"muted",values:n}];(0,r.useEffect)(()=>{if(n===void 0||n.length===0)return;let f;return l.current&&(f=new C(l.current.getContext("2d"),{type:s,data:{labels:o||d[0].values.map((e,t)=>`Entry ${t}`),datasets:d.map(e=>{let t=h(e.color||"muted");return{label:e.name,data:e.values,minBarLength:0,categoryPercentage:.9,backgroundColor:t,borderColor:t,borderWidth:s==="line"?2:0,pointRadius:0}})},options:{scales:{x:{display:s==="bar"||c,bounds:"data",stacked:!0,ticks:{display:!1},grid:{drawTicks:!1,display:!1},alignToPixels:!0},y:{display:c,bounds:"data",min:0,suggestedMax:1,stacked:!0,ticks:{includeBounds:!0,autoSkip:!0,maxTicksLimit:1,align:"start",callback:e=>typeof e=="number"&&e>0?u(e):null,font:{size:10,lineHeight:1}},grid:{tickBorderDash:[2],display:!0,tickLength:0},alignToPixels:!0,afterFit:e=>{e.paddingTop=1,e.paddingBottom=1}}},plugins:{crosshair:!1,legend:{display:!1},tooltip:{enabled:!1,external({tooltip:e}){E(e.opacity>0),N((0,a.jsx)(x,{embedded:!0,hideInspectActorsSection:!0,showHeader:!!o,altTitle:e.dataPoints[0].label,seriesData:e.dataPoints.map((t,R)=>({id:R,dataIndex:0,datasetIndex:0,label:t.dataset.label,color:t.dataset.borderColor,count:t.dataset.data?.[t.dataIndex]||0})),renderSeries:t=>t,renderCount:t=>u(t)}))}}},maintainAspectRatio:!1,interaction:{mode:"index",axis:"x",intersect:!1}}})),()=>{f?.destroy()}},[o,n]);let m=d[0].values.length,p=(0,y.default)(m>16?"w-64":m>8?"w-48":m>4?"w-32":"w-24",w);return P?(0,a.jsx)(T,{className:p}):(0,a.jsxs)("div",{className:p,children:[(0,a.jsx)("canvas",{ref:l}),(0,a.jsx)(v,{visible:L,overlay:D,placement:"bottom-start",padded:!1,children:(0,a.jsx)("div",{ref:I})})]})}function M(o){return typeof o[0]!="number"}export{G as a};
//# sourceMappingURL=/static/chunk-CEZSENEJ.js.map
