import{a as A}from"/static/chunk-UHZXOKW4.js";import{d as E}from"/static/chunk-VUSJMGUX.js";import{a as G,b as Q,d as U,e as V}from"/static/chunk-P6WLOCWZ.js";import{$d as D,Ao as i,Do as I,Sd as d,Ta as W,a as B,ce as J,fe as P,m as R,r as T,vo as X,xo as H,yo as M,ze as L}from"/static/chunk-RFJTZKD6.js";import{F as z,a as K}from"/static/chunk-3UDJFOQH.js";import{d as f,e as b,g as k,j as w}from"/static/chunk-SJXEOBQC.js";b();w();k();var m=f(B());var _=f(K());b();w();k();var C=f(B());var r=f(T());function F(){let{toggleSchemaShouldSync:s,openSyncMethodModal:u}=(0,C.useActions)(i),{databaseSchema:p}=(0,C.useValues)(i);return(0,r.jsxs)(r.Fragment,{children:[(0,r.jsx)("div",{className:"flex flex-col gap-2",children:(0,r.jsx)("div",{children:(0,r.jsx)(L,{emptyState:"No schemas found",dataSource:p,columns:[{width:0,key:"enabled",render:(l,t)=>(0,r.jsx)(D,{checked:t.should_sync,onChange:a=>{s(t,a)},disabledReason:t.sync_type===null?"Please set up a sync method first":void 0})},{title:"Table",key:"table",render:function(t,a){return a.table}},{title:"Rows",key:"rows",isHidden:!p.some(l=>l.rows),render:(l,t)=>t.rows!=null?t.rows:"Unknown"},{key:"sync_type",title:"Sync method",align:"right",tooltip:"Full refresh will refresh the full table on every sync, whereas incremental will only sync new and updated rows since the last sync",render:(l,t)=>t.sync_type?(0,r.jsx)("div",{className:"justify-end flex",children:(0,r.jsx)(d,{className:"my-1",size:"small",type:"secondary",onClick:()=>u(t),children:t.sync_type==="full_refresh"?"Full refresh":"Incremental"})}):(0,r.jsx)("div",{className:"justify-end flex",children:(0,r.jsx)(d,{className:"my-1",type:"primary",onClick:()=>u(t),children:"Set up"})})}]})})}),(0,r.jsx)(Z,{})]})}var Z=()=>{let{cancelSyncMethodModal:s,updateSchemaSyncType:u,toggleSchemaShouldSync:p}=(0,C.useActions)(i),{syncMethodModalOpen:l,currentSyncMethodModalSchema:t}=(0,C.useValues)(i);return t?(0,r.jsx)(J,{title:`Sync method for ${t.table}`,isOpen:l,onClose:s,children:(0,r.jsx)(G,{schema:t,onClose:s,onSave:(a,S,y)=>{a==="incremental"?u(t,a,S,y):u(t,a??null,null,null),p(t,!0),s()}})}):(0,r.jsx)(r.Fragment,{})};b();w();k();var x=f(B());var N=f(T()),O=()=>{let{sourceId:s,isWrapped:u}=(0,x.useValues)(i),{cancelWizard:p}=(0,x.useActions)(i),{dataWarehouseSources:l,dataWarehouseSourcesLoading:t}=(0,x.useValues)(H),S=l?.results.find(c=>c.id===s)?.schemas??[],y=c=>c.should_sync?c.status==="Running"?{status:"Syncing...",tagType:"primary"}:c.status==="Completed"?{status:"Completed",tagType:"success"}:{status:"Error",tagType:"danger"}:{status:"Not synced",tagType:"default"},g=[{title:"Table",key:"table",render:function(h,o){return o.name}},{title:"Status",key:"status",render:function(h,o){let{status:n,tagType:v}=y(o);return(0,N.jsx)(P,{type:v,children:n})}}];return u||g.push({key:"actions",width:0,render:function(h,o){if(o.table&&o.status==="Completed"){let n=U(o.table.name,o.table.columns);return(0,N.jsx)(d,{className:"my-1",type:"primary",onClick:p,to:I.insightNew({query:n}),children:"Query"})}return""}}),(0,N.jsx)("div",{className:"flex flex-col gap-2",children:(0,N.jsx)("div",{children:(0,N.jsx)(L,{emptyState:"No schemas selected",dataSource:S,loading:t,disableTableWhileLoading:!1,columns:g})})})};var e=f(T()),De={component:ee,logic:i};function ee(){let{closeWizard:s}=(0,m.useActions)(i);return(0,e.jsxs)(e.Fragment,{children:[(0,e.jsx)(X,{buttons:(0,e.jsx)(e.Fragment,{children:(0,e.jsx)(d,{type:"secondary",center:!0,"data-attr":"source-form-cancel-button",onClick:s,children:"Cancel"})})}),(0,e.jsx)(te,{})]})}function te({onComplete:s}){let u=i({onComplete:s}),{modalTitle:p,modalCaption:l,isWrapped:t,currentStep:a,isLoading:S,canGoBack:y,canGoNext:g,nextButtonText:c}=(0,m.useValues)(u),{onBack:h,onSubmit:o,onClear:n}=(0,m.useActions)(u),{tableLoading:v}=(0,m.useValues)(M);(0,_.useEffect)(()=>()=>{n()},[n]);let $=(0,_.useCallback)(()=>a===1?null:(0,e.jsxs)("div",{className:"mt-4 flex flex-row justify-end gap-2",children:[y&&(0,e.jsx)(d,{type:"secondary",center:!0,"data-attr":"source-modal-back-button",onClick:h,disabledReason:!y&&"You cant go back from here",children:"Back"}),(0,e.jsx)(d,{loading:S||v,disabledReason:!g&&"You cant click next yet",type:"primary",center:!0,onClick:()=>o(),"data-attr":"source-link",children:c})]}),[a,y,h,S,v,g,c,o]);return(0,e.jsxs)(e.Fragment,{children:[!t&&(0,e.jsx)(A,{}),(0,e.jsxs)(e.Fragment,{children:[(0,e.jsx)("h3",{children:p}),(0,e.jsx)("p",{children:l}),a===1?(0,e.jsx)(oe,{}):a===2?(0,e.jsx)(ne,{}):a===3?(0,e.jsx)(re,{}):a===4?(0,e.jsx)(ae,{}):(0,e.jsx)("div",{children:"Something went wrong..."}),$()]})]})}function oe(){let{connectors:s,manualConnectors:u,addToHubspotButtonUrl:p}=(0,m.useValues)(i),{selectConnector:l,toggleManualLinkFormVisible:t,onNext:a,setManualLinkingProvider:S}=(0,m.useActions)(i),{featureFlags:y}=(0,m.useValues)(R),g=o=>{o.name=="Hubspot"?window.open(p()):l(o),a()},c=o=>{t(!0),S(o)},h=s.filter(o=>!(o.name==="BigQuery"&&!y[z.BIGQUERY_DWH]));return(0,e.jsxs)(e.Fragment,{children:[(0,e.jsx)("h2",{className:"mt-4",children:"Managed by PostHog"}),(0,e.jsxs)("p",{children:["Data will be synced to PostHog and regularly refreshed."," ",(0,e.jsx)(W,{to:"https://posthog.com/docs/data-warehouse/setup#stripe",children:"Learn more"})]}),(0,e.jsx)(L,{dataSource:h,loading:!1,disableTableWhileLoading:!1,columns:[{title:"Source",width:0,render:function(o,n){return(0,e.jsx)(E,{type:n.name})}},{title:"Name",key:"name",render:(o,n)=>(0,e.jsx)("span",{className:"font-semibold text-sm gap-1",children:n.label??n.name})},{key:"actions",width:0,render:(o,n)=>(0,e.jsx)("div",{className:"flex flex-row justify-end",children:(0,e.jsx)(d,{onClick:()=>g(n),className:"my-2",type:"primary",children:"Link"})})}]}),(0,e.jsx)("h2",{className:"mt-4",children:"Self Managed"}),(0,e.jsxs)("p",{children:["Data will be queried directly from your data source that you manage."," ",(0,e.jsx)(W,{to:"https://posthog.com/docs/data-warehouse/setup#linking-a-custom-source",children:"Learn more"})]}),(0,e.jsx)(L,{dataSource:u,loading:!1,disableTableWhileLoading:!1,columns:[{title:"Source",width:0,render:(o,n)=>(0,e.jsx)(E,{type:n.type})},{title:"Name",key:"name",render:(o,n)=>(0,e.jsx)("span",{className:"font-semibold text-sm gap-1",children:n.name})},{key:"actions",width:0,render:(o,n)=>(0,e.jsx)("div",{className:"flex flex-row justify-end",children:(0,e.jsx)(d,{onClick:()=>c(n.type),className:"my-2",type:"primary",children:"Link"})})}]})]})}function ne(){let{selectedConnector:s}=(0,m.useValues)(i);return s?(0,e.jsx)(Q,{sourceConfig:s}):(0,e.jsx)(m.BindLogic,{logic:M,props:{id:"new"},children:(0,e.jsx)(V,{})})}function re(){return(0,e.jsx)(F,{})}function ae(){return(0,e.jsx)(O,{})}export{De as a,ee as b,te as c};
//# sourceMappingURL=/static/chunk-6WY34WKJ.js.map
