import{a as N,b as ce,c as le}from"/static/chunk-ETCXUTLK.js";import{a as ie,b as ae,c as d,d as ue}from"/static/chunk-442FMYLN.js";import{a as oe}from"/static/chunk-TKIMSWKH.js";import"/static/chunk-ZH744EYW.js";import"/static/chunk-6BOQTIB6.js";import"/static/chunk-FT4MFWRB.js";import{b as se,j as te}from"/static/chunk-YDKHEMDP.js";import"/static/chunk-7SO55T25.js";import"/static/chunk-KBNOIM2W.js";import"/static/chunk-BB32DDTD.js";import"/static/chunk-QB3AUFV2.js";import"/static/chunk-PWG7LMNW.js";import{a as re}from"/static/chunk-CEZSENEJ.js";import"/static/chunk-GOBPXP3Z.js";import{$d as J,$n as Z,Do as R,Eo as ne,Io as Q,Pg as M,Pl as j,Sa as z,Sd as I,Ta as U,Wb as q,Wd as V,Wh as B,Xn as W,a as v,ao as $,b as O,bo as Y,ch as D,ee as X,f as fe,g as ye,h as ke,oe as H,pe as A,r as b,se as K,vo as ee}from"/static/chunk-TW5IU73S.js";import"/static/chunk-XPJ4MQJV.js";import"/static/chunk-KQJ3FYBQ.js";import{Ua as C,da as pe,hb as F}from"/static/chunk-3UDJFOQH.js";import"/static/chunk-HHT4SG7V.js";import"/static/chunk-K7LQKAJG.js";import"/static/chunk-QQTK3LZH.js";import"/static/chunk-IJQNM355.js";import"/static/chunk-4CN6THWS.js";import"/static/chunk-272RTCFX.js";import"/static/chunk-2ROB4QWU.js";import"/static/chunk-ALT2ZZSO.js";import"/static/chunk-UE6SLBBN.js";import"/static/chunk-GINZUAUY.js";import"/static/chunk-SQELCOUW.js";import"/static/chunk-IGYUTZ65.js";import"/static/chunk-YM6UBNGD.js";import"/static/chunk-C6TQ5FFZ.js";import"/static/chunk-GXGA523B.js";import"/static/chunk-N4MMWRNK.js";import"/static/chunk-NRLAI7OY.js";import"/static/chunk-LVVHNICT.js";import"/static/chunk-2AXSSSSX.js";import"/static/chunk-DGXQI7RB.js";import"/static/chunk-HUCRWDLX.js";import"/static/chunk-RFEQG3YN.js";import"/static/chunk-PUISI233.js";import{d as l,e as k,g as T,j as h}from"/static/chunk-SJXEOBQC.js";k();h();T();var de=l(ke()),a=l(v());k();h();T();var u=l(v());var x=(0,u.kea)([(0,u.path)(["scenes","error-tracking","errorTrackingDataNodeLogic"]),(0,u.props)({}),(0,u.connect)(({key:r,query:e})=>({values:[B({key:r,query:e}),["response"]],actions:[B({key:r,query:e}),["setResponse","loadData"]]})),(0,u.actions)({mergeIssues:r=>({ids:r}),assignIssue:(r,e)=>({id:r,assignee:e})}),(0,u.listeners)(({values:r,actions:e})=>({mergeIssues:async({ids:n})=>{let o=r.response?.results,t=o.filter(({id:c})=>n.includes(c)),i=t.shift();if(i&&t.length>0){let c=t.map(S=>S.id),y=W(i,t);e.setResponse({...r.response,results:o.filter(({id:S})=>!c.includes(S)).map(S=>y.id===S.id?y:S)}),await Q.errorTracking.mergeInto(i.id,c),e.loadData(!0)}},assignIssue:async({id:n,assignee:o})=>{let t=r.response;if(t){let i=t.results,c=i.findIndex(y=>y.id===n);if(c>-1){let y={...i[c],assignee:o};i.splice(c,1,y),e.setResponse({...t,results:i}),await Q.errorTracking.assignIssue(y.id,o),e.loadData(!0)}}}}))]);k();h();T();var E=l(v());k();h();T();var L=l(pe()),g=l(v()),p=l(fe()),ge=l(ye());var f=(0,g.kea)([(0,g.path)(["scenes","error-tracking","errorTrackingSceneLogic"]),(0,g.connect)({values:[d,["dateRange","assignee","filterTestAccounts","filterGroup","customSparklineConfig","searchQuery"]],actions:[d,["setAssignee","setDateRange","setFilterGroup","setSearchQuery","setFilterTestAccounts"]]}),(0,g.actions)({setOrderBy:r=>({orderBy:r}),setStatus:r=>({status:r}),setSelectedIssueIds:r=>({ids:r})}),(0,g.reducers)({orderBy:["last_seen",{persist:!0},{setOrderBy:(r,{orderBy:e})=>e}],status:["active",{persist:!0},{setStatus:(r,{status:e})=>e}],selectedIssueIds:[[],{setSelectedIssueIds:(r,{ids:e})=>e}]}),(0,g.selectors)(({values:r})=>({query:[e=>[e.orderBy,e.status,e.dateRange,e.assignee,e.filterTestAccounts,e.filterGroup,e.searchQuery],(e,n,o,t,i,c,y)=>se({orderBy:e,status:n,dateRange:o,assignee:t,filterTestAccounts:i,filterGroup:c,customVolume:r.customSparklineConfig,searchQuery:y,columns:["error","volume","occurrences","sessions","users","assignee"]})]})),(0,ge.subscriptions)(({actions:r})=>({query:()=>r.setSelectedIssueIds([])})),(0,p.actionToUrl)(({values:r})=>{let e=()=>{let n={orderBy:r.orderBy,status:r.status,filterTestAccounts:r.filterTestAccounts};return r.searchQuery&&(n.searchQuery=r.searchQuery),C(r.filterGroup,ae)||(n.filterGroup=r.filterGroup),C(r.dateRange,ie)||(n.dateRange=r.dateRange),C(n,p.router.values.searchParams)?[p.router.values.location.pathname,p.router.values.searchParams,p.router.values.hashParams,{replace:!1}]:[p.router.values.location.pathname,n,p.router.values.hashParams,{replace:!0}]};return{setOrderBy:()=>e(),setStatus:()=>e(),setDateRange:()=>e(),setFilterGroup:()=>e(),setSearchQuery:()=>e(),setFilterTestAccounts:()=>e()}}),(0,p.urlToAction)(({actions:r,values:e})=>({"*":(o,t)=>{t.orderBy&&!(0,L.default)(t.orderBy,e.orderBy)&&r.setOrderBy(t.orderBy),t.status&&!(0,L.default)(t.status,e.status)&&r.setStatus(t.status),t.dateRange&&!(0,L.default)(t.dateRange,e.dateRange)&&r.setDateRange(t.dateRange),t.filterGroup&&!(0,L.default)(t.filterGroup,e.filterGroup)&&r.setFilterGroup(t.filterGroup),t.filterTestAccounts&&!(0,L.default)(t.filterTestAccounts,e.filterTestAccounts)&&r.setFilterTestAccounts(t.filterTestAccounts),t.searchQuery&&!(0,L.default)(t.searchQuery,e.searchQuery)&&r.setSearchQuery(t.searchQuery)}}))]);var m=l(b()),me=()=>{let{assignee:r}=(0,E.useValues)(d),{setAssignee:e}=(0,E.useActions)(d),{orderBy:n,status:o}=(0,E.useValues)(f),{setOrderBy:t,setStatus:i}=(0,E.useActions)(f);return(0,m.jsxs)("div",{className:"flex justify-end space-x-2 py-2",children:[(0,m.jsxs)("div",{className:"flex items-center gap-1",children:[(0,m.jsx)("span",{children:"Status:"}),(0,m.jsx)(A,{onSelect:i,onChange:i,value:o,options:[{value:"all",label:"All"},{value:"active",label:"Active"},{value:"resolved",label:"Resolved"}],size:"small"})]}),(0,m.jsxs)("div",{className:"flex items-center gap-1",children:[(0,m.jsx)("span",{children:"Sort by:"}),(0,m.jsx)(A,{onSelect:t,onChange:t,value:n,options:[{value:"last_seen",label:"Last seen"},{value:"first_seen",label:"First seen"},{value:"occurrences",label:"Occurrences"},{value:"users",label:"Users"},{value:"sessions",label:"Sessions"}],size:"small"})]}),(0,m.jsxs)("div",{className:"flex items-center gap-1",children:[(0,m.jsx)("span",{children:"Assigned to:"}),(0,m.jsx)(N,{showName:!0,showIcon:!1,assignee:r,onChange:c=>e(c),unassignedLabel:"Any user",type:"secondary",size:"small"})]})]})};var s=l(b()),kr={component:Te,logic:f};function Te(){let{hasSentExceptionEvent:r,hasSentExceptionEventLoading:e}=(0,a.useValues)(d),{query:n,selectedIssueIds:o}=(0,a.useValues)(f),t={dashboardItemId:"new-ErrorTrackingQuery"},i={columns:{error:{width:"50%",render:Ie},occurrences:{align:"center",render:G},sessions:{align:"center",render:G},users:{align:"center",render:G},volume:{renderTitle:Se,render:Le},assignee:{render:Ee}},showOpenEditorButton:!1,insightProps:t,emptyStateHeading:"No issues found",emptyStateDetail:"Try changing the date range, changing the filters or removing the assignee."};return(0,s.jsx)(ue,{children:(0,s.jsxs)(a.BindLogic,{logic:x,props:{query:n,key:j(t)},children:[(0,s.jsx)(ve,{}),e?null:r?(0,s.jsx)(oe,{text:"Error tracking is currently in beta. Thanks for taking part! We'd love to hear what you think."}):(0,s.jsx)(Ce,{}),(0,s.jsx)(ce,{}),(0,s.jsx)(X,{className:"mt-2"}),o.length===0?(0,s.jsx)(me,{}):(0,s.jsx)(he,{}),(0,s.jsx)(te,{query:n,context:i})]})})}var he=()=>{let{selectedIssueIds:r}=(0,a.useValues)(f),{setSelectedIssueIds:e}=(0,a.useActions)(f),{mergeIssues:n}=(0,a.useActions)(x);return(0,s.jsxs)("div",{className:"sticky top-[var(--breadcrumbs-height-compact)] z-20 py-2 bg-primary flex space-x-1",children:[(0,s.jsx)(I,{type:"secondary",size:"small",onClick:()=>e([]),children:"Unselect all"}),r.length>1&&(0,s.jsx)(I,{type:"secondary",size:"small",onClick:()=>{n(r),e([])},children:"Merge"})]})},Le=r=>{let{sparklineSelectedPeriod:e,customSparklineConfig:n}=(0,a.useValues)(d),o=r.record;if(!o.aggregations)return null;let[t,i]=e==="24h"?[o.aggregations.volumeDay,Z]:e==="30d"?[o.aggregations.volumeMonth,$]:n?[o.aggregations.customVolume,Y(n)]:[null,null];return t?(0,s.jsx)(re,{className:"h-8",data:t,labels:i}):null},Se=({columnName:r})=>{let{sparklineSelectedPeriod:e,sparklineOptions:n}=(0,a.useValues)(d),{setSparklineSelectedPeriod:o}=(0,a.useActions)(d);return e&&n?(0,s.jsxs)("div",{className:"flex justify-between items-center min-w-64",children:[(0,s.jsx)("div",{children:r}),(0,s.jsx)(H,{size:"xsmall",value:e,options:Object.values(n),onChange:o})]}):null},Ie=r=>{let{selectedIssueIds:e}=(0,a.useValues)(f),{setSelectedIssueIds:n}=(0,a.useActions)(f),o=r.record,t=e.includes(o.id);return(0,s.jsxs)("div",{className:"flex items-start space-x-1.5 group",children:[(0,s.jsx)(J,{className:(0,de.default)("pt-1 group-hover:visible",!t&&"invisible"),checked:t,onChange:i=>{n(i?[...new Set([...e,o.id])]:e.filter(c=>c!=o.id))}}),(0,s.jsx)(M,{title:o.name||"Unknown Type",description:(0,s.jsxs)("div",{className:"space-y-1",children:[(0,s.jsx)("div",{className:"line-clamp-1",children:o.description}),(0,s.jsxs)("div",{className:"space-x-1",children:[(0,s.jsx)(D,{time:o.first_seen,className:"border-dotted border-b"}),(0,s.jsx)("span",{children:"|"}),o.last_seen?(0,s.jsx)(D,{time:o.last_seen,className:"border-dotted border-b"}):(0,s.jsx)(K,{})]})]}),className:"flex-1",to:R.errorTrackingIssue(o.id),onClick:()=>{let i=le({id:o.id});i.mount(),i.actions.setIssue(o)}})]})},G=({record:r,columnName:e})=>{let o=r.aggregations[e];return e==="sessions"&&o===0?(0,s.jsx)(z,{title:"No $session_id was set for any event in this issue",delayMs:0,children:"-"}):(0,s.jsx)(s.Fragment,{children:F(o)})},Ee=r=>{let{assignIssue:e}=(0,a.useActions)(x),n=r.record;return(0,s.jsx)("div",{className:"flex justify-center",children:(0,s.jsx)(N,{assignee:n.assignee,onChange:o=>e(n.id,o)})})},ve=()=>{let{user:r}=(0,a.useValues)(ne);return(0,s.jsx)(ee,{buttons:(0,s.jsxs)(s.Fragment,{children:[r?.is_staff?(0,s.jsx)(I,{onClick:()=>{O.captureException(new Error("Oh my!"))},children:"Send an exception"}):null,(0,s.jsx)(I,{to:"https://posthog.com/docs/error-tracking",type:"secondary",targetBlank:!0,children:"Documentation"}),(0,s.jsx)(I,{to:R.errorTrackingConfiguration(),type:"secondary",icon:(0,s.jsx)(q,{}),children:"Configure"})]})})},Ce=()=>(0,s.jsxs)(V,{type:"warning",className:"my-4",children:[(0,s.jsx)("p",{children:(0,s.jsx)("strong",{children:"No Exception events have been detected!"})}),(0,s.jsxs)("p",{children:["To use the Error tracking product, please"," ",(0,s.jsx)(U,{to:"https://posthog.com/docs/error-tracking/installation",children:"enable exception capture within the PostHog SDK"})," ","(otherwise it'll be a little empty!)"]})]});export{Te as ErrorTrackingScene,kr as scene};
//# sourceMappingURL=/static/ErrorTrackingScene-AP6CGL3O.js.map
