import{a as p}from"/static/chunk-TBIQSJ6Q.js";import{d as C}from"/static/chunk-B2IEXZN7.js";import"/static/chunk-EIH6KTHG.js";import"/static/chunk-NEPY3GOZ.js";import"/static/chunk-TUL3J7MM.js";import{a as A}from"/static/chunk-FZRQH23Q.js";import{a as _}from"/static/chunk-AZNOCCXL.js";import"/static/chunk-KRWBS22W.js";import"/static/chunk-OFFTP67N.js";import"/static/chunk-Q2TQBXTL.js";import"/static/chunk-WTEAZEML.js";import"/static/chunk-TBYU2GKH.js";import{a as k}from"/static/chunk-DJ5KSU5H.js";import"/static/chunk-MOVKLCV5.js";import"/static/chunk-FT4MFWRB.js";import{j as F}from"/static/chunk-YDKHEMDP.js";import"/static/chunk-7SO55T25.js";import"/static/chunk-HRNZBUVG.js";import"/static/chunk-Y35PDO57.js";import"/static/chunk-KBNOIM2W.js";import"/static/chunk-BB32DDTD.js";import"/static/chunk-QB3AUFV2.js";import"/static/chunk-PWG7LMNW.js";import"/static/chunk-CEZSENEJ.js";import"/static/chunk-GOBPXP3Z.js";import{Cg as E,Do as a,Gm as T,Ja as x,Rd as w,Sd as r,Xa as L,a as O,ch as l,de as D,ee as o,fe as N,r as b,up as B,vo as P}from"/static/chunk-TW5IU73S.js";import"/static/chunk-XPJ4MQJV.js";import"/static/chunk-KQJ3FYBQ.js";import{a as M}from"/static/chunk-3UDJFOQH.js";import"/static/chunk-HHT4SG7V.js";import"/static/chunk-K7LQKAJG.js";import"/static/chunk-QQTK3LZH.js";import"/static/chunk-IJQNM355.js";import"/static/chunk-4CN6THWS.js";import"/static/chunk-272RTCFX.js";import"/static/chunk-2ROB4QWU.js";import"/static/chunk-ALT2ZZSO.js";import"/static/chunk-UE6SLBBN.js";import"/static/chunk-GINZUAUY.js";import"/static/chunk-SQELCOUW.js";import"/static/chunk-IGYUTZ65.js";import"/static/chunk-YM6UBNGD.js";import"/static/chunk-C6TQ5FFZ.js";import"/static/chunk-GXGA523B.js";import"/static/chunk-N4MMWRNK.js";import"/static/chunk-NRLAI7OY.js";import"/static/chunk-LVVHNICT.js";import"/static/chunk-2AXSSSSX.js";import"/static/chunk-DGXQI7RB.js";import"/static/chunk-HUCRWDLX.js";import"/static/chunk-RFEQG3YN.js";import"/static/chunk-PUISI233.js";import{d as n,e as y,g,j as h}from"/static/chunk-SJXEOBQC.js";y();h();g();var s=n(O());var S=n(M());var e=n(b()),ge={component:V,logic:p,paramsToProps:({params:{id:m}})=>({id:m})};function V(m={}){let c=p(m),{definition:t,definitionLoading:f,definitionMissing:Q,hasTaxonomyFeatures:v,singular:u,isEvent:i,isProperty:d}=(0,s.useValues)(c),{deleteDefinition:H}=(0,s.useActions)(c),I=(0,S.useMemo)(()=>({kind:"DataTableNode",source:{kind:"EventsQuery",select:B("EventsQuery"),event:t.name},full:!0,showEventFilter:!1}),[t.name]);return f?(0,e.jsx)(w,{sceneLevel:!0}):Q?(0,e.jsx)(T,{object:"event"}):(0,e.jsxs)(e.Fragment,{children:[(0,e.jsx)(P,{buttons:(0,e.jsxs)(e.Fragment,{children:[i&&(0,e.jsx)(r,{type:"secondary",to:a.replay("home",{filter_group:{type:"AND",values:[{type:"AND",values:[{id:t.name,type:"events",order:0,name:t.name}]}]}}),sideIcon:(0,e.jsx)(x,{}),"data-attr":"event-definition-view-recordings",children:"View recordings"}),(0,e.jsx)(r,{"data-attr":"delete-definition",type:"secondary",status:"danger",onClick:()=>D.open({title:`Delete this ${u} definition?`,description:(0,e.jsxs)(e.Fragment,{children:[(0,e.jsxs)("p",{children:[(0,e.jsx)("strong",{children:L(t.name,i?"events":"event_properties")})," ","will no\xA0longer appear in\xA0selectors. Associated\xA0data will remain in\xA0the\xA0database."]}),(0,e.jsxs)("p",{children:["This\xA0definition will be recreated if\xA0the\xA0",u," is\xA0ever seen again in\xA0the\xA0event\xA0stream."]})]}),primaryButton:{status:"danger",children:"Delete definition",onClick:()=>H()},secondaryButton:{children:"Cancel"},width:448}),tooltip:"Delete this definition. Associated data will remain.",children:"Delete"}),(v||d)&&(0,e.jsx)(r,{"data-attr":"edit-definition",type:"secondary",to:i?a.eventDefinitionEdit(t.id):a.propertyDefinitionEdit(t.id),children:"Edit"})]})}),(0,e.jsxs)("div",{className:"space-y-2",children:[t.description||d||v?(0,e.jsx)(A,{multiline:!0,name:"description",markdown:!0,value:t.description||"",placeholder:"Description (optional)",mode:"view","data-attr":"definition-description-view",className:"definition-description",compactButtons:!0,maxLength:600}):null,(0,e.jsx)(E,{tags:t.tags??[],"data-attr":"definition-tags-view",className:"definition-tags",saving:f}),(0,e.jsx)(k,{at:t.updated_at,by:t.updated_by}),(0,e.jsxs)("div",{className:"flex flex-wrap items-center gap-2 text-secondary",children:[(0,e.jsx)("div",{children:"Raw event name:"}),(0,e.jsx)(N,{className:"font-mono",children:t.name})]})]}),(0,e.jsx)(o,{className:"my-6"}),(0,e.jsxs)("div",{className:"flex flex-wrap",children:[i&&t.created_at&&(0,e.jsxs)("div",{className:"flex-1 flex flex-col",children:[(0,e.jsx)("h5",{children:"First seen"}),(0,e.jsx)("b",{children:(0,e.jsx)(l,{time:t.created_at})})]}),i&&t.last_seen_at&&(0,e.jsxs)("div",{className:"flex-1 flex flex-col",children:[(0,e.jsx)("h5",{children:"Last seen"}),(0,e.jsx)("b",{children:(0,e.jsx)(l,{time:t.last_seen_at})})]}),d&&(0,e.jsxs)("div",{className:"flex-1 flex flex-col",children:[(0,e.jsx)("h5",{children:"Property type"}),(0,e.jsx)("b",{children:t.property_type??"-"})]})]}),(0,e.jsx)(o,{className:"my-6"}),i&&t.id!=="new"&&(0,e.jsxs)(e.Fragment,{children:[(0,e.jsx)(C,{definition:t}),(0,e.jsx)(o,{className:"my-6"}),(0,e.jsx)("h2",{className:"flex-1 subtitle",children:"Connected destinations"}),(0,e.jsx)("p",{children:"Get notified via Slack, webhooks or more whenever this event is captured."}),(0,e.jsx)(_,{logicKey:"event-definitions",type:"destination",filters:{events:[{id:`${t.name}`,type:"events"}]}}),(0,e.jsx)(o,{className:"my-6"}),(0,e.jsx)("h3",{children:"Matching events"}),(0,e.jsx)("p",{children:"This is the list of recent events that match this definition."}),(0,e.jsx)(F,{query:I})]})]})}export{V as DefinitionView,ge as scene};
//# sourceMappingURL=/static/DefinitionView-ZQDSJZ3A.js.map
