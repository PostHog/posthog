import{a as S}from"/static/chunk-RSTRTBMR.js";import{Io as u,Ta as y,Wd as l,r as d}from"/static/chunk-RFJTZKD6.js";import{a as I}from"/static/chunk-3UDJFOQH.js";import{d as r,e as c,g as p,j as m}from"/static/chunk-SJXEOBQC.js";c();m();p();c();m();p();var b=r(I()),o=r(d());function v({integration:e,schema:h}){let s=(0,b.useMemo)(()=>{let i=[];return[e.config.scope,e.config.scopes].map(n=>{typeof n=="string"&&(i.push(n.split(" ")),i.push(n.split(","))),typeof n=="object"&&i.push(n)}),i.filter(n=>typeof n=="object").reduce((n,g)=>n.length>g.length?n:g,[])},[e.config]),f=(h?.requiredScopes?.split(" ")||[]).filter(i=>!s.includes(i));return f.length===0||s.length===0?(0,o.jsx)(o.Fragment,{}):(0,o.jsx)("div",{className:"p-2",children:(0,o.jsxs)(l,{type:"error",action:{children:"Reconnect",disableClientSideRouting:!0,to:u.integrations.authorizeUrl({kind:e.kind,next:window.location.pathname})},children:[(0,o.jsxs)("span",{children:["Required scopes are missing: [",f.join(", "),"]."]}),e.kind==="hubspot"?(0,o.jsxs)("span",{children:["Note that some features may not be available on your current HubSpot plan. Check out"," ",(0,o.jsx)(y,{to:"https://developers.hubspot.com/beta-docs/guides/apps/authentication/scopes",children:"this page"})," ","for more details."]}):null]})})}var t=r(d());function A({integration:e,suffix:h,schema:s}){let a=e.errors&&e.errors?.split(",")||[];return(0,t.jsxs)("div",{className:"rounded border bg-surface-primary",children:[(0,t.jsxs)("div",{className:"flex justify-between items-center p-2",children:[(0,t.jsxs)("div",{className:"flex items-center gap-4 ml-2",children:[(0,t.jsx)("img",{src:e.icon_url,className:"h-10 w-10 rounded"}),(0,t.jsxs)("div",{children:[(0,t.jsxs)("div",{children:["Connected to ",(0,t.jsx)("strong",{children:e.display_name})]}),e.created_by?(0,t.jsx)(S,{at:e.created_at,by:e.created_by,prefix:"Updated",className:"text-secondary"}):null]})]}),h]}),a.length>0?(0,t.jsx)("div",{className:"p-2",children:(0,t.jsx)(l,{type:"error",action:{children:"Reconnect",disableClientSideRouting:!0,to:u.integrations.authorizeUrl({kind:e.kind,next:window.location.pathname})},children:a[0]==="TOKEN_REFRESH_FAILED"?"Authentication token could not be refreshed. Please reconnect.":`There was an error with this integration: ${a[0]}`})}):(0,t.jsx)(v,{integration:e,schema:s})]})}export{A as a};
//# sourceMappingURL=/static/chunk-TF53AUIP.js.map
