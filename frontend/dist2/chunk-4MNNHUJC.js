import{a as g,d as h}from"/static/chunk-MHUMFW53.js";import{a as M}from"/static/chunk-N2KORDXB.js";import{a as i}from"/static/chunk-KHKNIVWH.js";import{Sd as T,a as y,ce as w,ie as C,je as F,ji as N,r as c}from"/static/chunk-RFJTZKD6.js";import{Tb as V,a as E}from"/static/chunk-3UDJFOQH.js";import{d as r,e as d,g as n,j as p}from"/static/chunk-SJXEOBQC.js";d();p();n();var o=r(y());d();p();n();var l=r(y()),k=r(E());var t=r(c());function x(){let{activeDashboardTemplate:s}=(0,l.useValues)(i),m=h({variables:s?.variables||[]}),{variables:b}=(0,l.useValues)(m),{setVariable:u,setVariables:f}=(0,l.useActions)(m);return(0,k.useEffect)(()=>{f(s?.variables||[])},[s]),(0,t.jsx)("div",{className:"mb-4 DashboardTemplateVariables max-w-192",children:b.map((a,v)=>(0,t.jsxs)("div",{className:"mb-6",children:[(0,t.jsxs)("div",{className:"mb-2",children:[(0,t.jsx)(F,{showOptional:!a.required,info:(0,t.jsx)(t.Fragment,{children:a.description}),children:a.name}),(0,t.jsx)("p",{className:"text-sm text-secondary",children:a.description})]}),(0,t.jsx)("div",{children:(0,t.jsx)(N,{filters:{insight:"TRENDS",events:[a.default]},setFilters:L=>{u(a.name,L)},typeKey:"variable_"+a.name,hideDeleteBtn:!0,hideRename:!0,hideDuplicate:!0,entitiesLimit:1})})]},v))})}var e=r(c());function oe(){let s=(0,o.useMountedLogic)(i),{hideNewDashboardModal:m,clearActiveDashboardTemplate:b,createDashboardFromTemplate:u}=(0,o.useActions)(i),{newDashboardModalVisible:f,activeDashboardTemplate:a,variableSelectModalVisible:v}=(0,o.useValues)(i),{variables:L}=(0,o.useValues)(h),D=M({scope:s.props.featureFlagId?"feature_flag":"default"}),{templateFilter:B}=(0,o.useValues)(D),{setTemplateFilter:_}=(0,o.useActions)(D),A=s.props.featureFlagId?(0,e.jsx)(g,{scope:"feature_flag"}):(0,e.jsx)(g,{});return(0,e.jsx)(w,{onClose:m,isOpen:f,title:a?"Choose your events":"Create a dashboard","data-attr":"new-dashboard-chooser",description:a?(0,e.jsxs)("p",{children:["The ",(0,e.jsx)("i",{children:a.template_name})," template requires you to choose"," ",V((a.variables||[]).length,"event","events",!0),"."]}):(0,e.jsxs)("div",{className:"flex flex-col gap-2",children:[(0,e.jsx)("div",{children:"Choose a template or start with a blank slate"}),(0,e.jsx)("div",{children:(0,e.jsx)(C,{type:"search",placeholder:"Filter templates",onChange:_,value:B,fullWidth:!0})})]}),footer:a?(0,e.jsxs)(e.Fragment,{children:[v?(0,e.jsx)("div",{}):(0,e.jsx)(T,{onClick:b,type:"secondary",children:"Back"}),(0,e.jsx)(T,{onClick:()=>{a&&u(a,L)},type:"primary",children:"Create"})]}):null,children:(0,e.jsx)("div",{className:"NewDashboardModal",children:a?(0,e.jsx)(x,{}):A})})}export{oe as a};
//# sourceMappingURL=/static/chunk-4MNNHUJC.js.map
