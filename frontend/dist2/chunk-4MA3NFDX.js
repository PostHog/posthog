import{h as X}from"/static/chunk-L6OS4YDC.js";import{a as h}from"/static/chunk-HOCRDURT.js";import{a as C}from"/static/chunk-LZWHW4MC.js";import{a as G}from"/static/chunk-DYVMG6MY.js";import{b as j,d as z}from"/static/chunk-OKGJSIGC.js";import{$i as W,Cg as F,Do as i,Eo as J,Gc as y,Hc as k,Ko as O,Pg as P,Sa as c,Sd as n,Ta as w,_i as R,a as ne,ac as D,bd as T,cg as d,ee as g,ie as B,kc as N,km as L,lm as _,ne as E,r as S,ve as I,ze as M}from"/static/chunk-RFJTZKD6.js";import{d as f,e as v,g as A,j as x}from"/static/chunk-SJXEOBQC.js";v();x();A();var o=f(ne());var e=f(S());function Ve(){let{dashboardsLoading:p}=(0,o.useValues)(L),{dashboards:b,filters:r}=(0,o.useValues)(h);return(0,e.jsx)(de,{dashboards:b,dashboardsLoading:p,filters:r})}function de({dashboards:p,dashboardsLoading:b,filters:r,extraActions:H,hideActions:U}){let{unpinDashboard:V,pinDashboard:K}=(0,o.useActions)(L),{setFilters:l,tableSortingChanged:q}=(0,o.useActions)(h),{tableSorting:Q}=(0,o.useValues)(h),{hasAvailableFeature:Y}=(0,o.useValues)(J),{currentTeam:Z}=(0,o.useValues)(O),{showDuplicateDashboardModal:$}=(0,o.useActions)(W),{showDeleteDashboardModal:ee}=(0,o.useActions)(R),ae=[{width:0,dataIndex:"pinned",render:function(t,{id:a}){return(0,e.jsx)(n,{size:"small",onClick:t?()=>V(a,"dashboards_list"):()=>K(a,"dashboards_list"),tooltip:t?"Unpin dashboard":"Pin dashboard",icon:t?(0,e.jsx)(k,{}):(0,e.jsx)(y,{})})}},{title:"Name",dataIndex:"name",width:"40%",render:function(t,{id:a,name:u,description:m,is_shared:oe,effective_privilege_level:re}){let se=a===Z?.primary_dashboard,te=re>=37;return(0,e.jsx)(P,{to:i.dashboard(a),title:(0,e.jsxs)(e.Fragment,{children:[(0,e.jsx)("span",{"data-attr":"dashboard-name",children:u||"Untitled"}),oe&&(0,e.jsx)(c,{title:"This dashboard is shared publicly.",children:(0,e.jsx)(T,{className:"ml-1 text-base text-link"})}),!te&&(0,e.jsx)(c,{title:X,children:(0,e.jsx)(N,{className:"ml-1 text-base text-secondary"})}),se&&(0,e.jsx)(c,{title:"The primary dashboard is shown on the project home page.",children:(0,e.jsx)("span",{children:(0,e.jsx)(D,{className:"ml-1 text-base text-warning"})})})]}),description:m})},sorter:_},...Y("tagging")?[{title:"Tags",dataIndex:"tags",render:function(t){return t?(0,e.jsx)(F,{tags:t,staticOnly:!0}):null}}]:[],z(),j(),U?{}:{width:0,render:function(t,{id:a,name:u,user_access_level:m}){return(0,e.jsx)(I,{overlay:(0,e.jsxs)(e.Fragment,{children:[(0,e.jsx)(n,{to:i.dashboard(a),onClick:()=>{d({id:a}).mount(),d({id:a}).actions.setDashboardMode(null,"dashboards_list")},fullWidth:!0,children:"View"}),(0,e.jsx)(C,{userAccessLevel:m,minAccessLevel:"editor",resourceType:"dashboard",to:i.dashboard(a),onClick:()=>{d({id:a}).mount(),d({id:a}).actions.setDashboardMode("edit","dashboards_list")},fullWidth:!0,children:"Edit"}),(0,e.jsx)(n,{onClick:()=>{$(a,u)},fullWidth:!0,children:"Duplicate"}),(0,e.jsx)(g,{}),(0,e.jsx)(E,{icon:(0,e.jsx)(D,{className:"text-warning"}),fullWidth:!0,status:"warning",children:(0,e.jsxs)("span",{className:"text-secondary",children:["Change the default dashboard",(0,e.jsx)("br",{}),"from the ",(0,e.jsx)(w,{to:i.projectHomepage(),children:"project home page"}),"."]})}),(0,e.jsx)(g,{}),(0,e.jsx)(C,{userAccessLevel:m,minAccessLevel:"editor",resourceType:"dashboard",onClick:()=>{ee(a)},fullWidth:!0,status:"danger",children:"Delete dashboard"})]})})}}];return(0,e.jsxs)(e.Fragment,{children:[(0,e.jsxs)("div",{className:"flex justify-between gap-2 flex-wrap mb-4",children:[(0,e.jsx)(B,{type:"search",placeholder:"Search for dashboards",onChange:s=>l({search:s}),value:r.search}),(0,e.jsxs)("div",{className:"flex items-center gap-4 flex-wrap",children:[(0,e.jsxs)("div",{className:"flex items-center gap-2",children:[(0,e.jsx)("span",{children:"Filter to:"}),(0,e.jsx)("div",{className:"flex items-center gap-2",children:(0,e.jsx)(n,{active:r.pinned,type:"secondary",size:"small",onClick:()=>l({pinned:!r.pinned}),icon:(0,e.jsx)(y,{}),children:"Pinned"})}),(0,e.jsx)("div",{className:"flex items-center gap-2",children:(0,e.jsx)(n,{active:r.shared,type:"secondary",size:"small",onClick:()=>l({shared:!r.shared}),icon:(0,e.jsx)(T,{}),children:"Shared"})})]}),(0,e.jsxs)("div",{className:"flex items-center gap-2",children:[(0,e.jsx)("span",{children:"Created by:"}),(0,e.jsx)(G,{value:r.createdBy==="All users"?null:r.createdBy,onChange:s=>l({createdBy:s?.uuid||"All users"})})]}),H]})]}),(0,e.jsx)(M,{"data-attr":"dashboards-table",pagination:{pageSize:100},dataSource:p,rowKey:"id",rowClassName:s=>s._highlight?"highlighted":null,columns:ae,loading:b,defaultSorting:Q,onSort:q,emptyState:"No dashboards matching your filters!",nouns:["dashboard","dashboards"]})]})}export{Ve as a,de as b};
//# sourceMappingURL=/static/chunk-4MA3NFDX.js.map
