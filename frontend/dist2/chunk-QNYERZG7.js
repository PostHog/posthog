import{$e as p,Od as B,Sd as i,Yi as N,a as W,ie as M,r as w}from"/static/chunk-TW5IU73S.js";import{Ja as m,a as D}from"/static/chunk-3UDJFOQH.js";import{d as l,e as g,g as v,j as P}from"/static/chunk-SJXEOBQC.js";g();P();v();var a=l(W());var o=l(D());var e=l(w());function j({defaultLabel:d="Any user",allowNone:x=!0,value:n,excludedMembers:C=[],onChange:S,children:f,...U}){let{meFirstMembers:r,filteredMembers:k,search:y,membersLoading:z}=(0,a.useValues)(p),{ensureAllMembersLoaded:T,setSearch:A}=(0,a.useActions)(p),[u,h]=(0,o.useState)(!1),c=typeof n=="string"?"uuid":"id",t=(0,o.useMemo)(()=>n?r.find(s=>s.user[c]===n)?.user??null:null,[n,r,c]),b=s=>{h(!1),S(s)};(0,o.useEffect)(()=>{u&&T()},[u]);let L=k.filter(s=>!C.includes(s.user[c]));return(0,e.jsx)(B,{closeOnClickInside:!1,visible:u,matchWidth:!1,actionable:!0,onVisibilityChange:s=>h(s),overlay:(0,e.jsxs)("div",{className:"max-w-100 space-y-2 overflow-hidden",children:[(0,e.jsx)(M,{type:"search",placeholder:"Search",autoFocus:!0,value:y,onChange:A,fullWidth:!0}),(0,e.jsxs)("ul",{className:"space-y-px",children:[x&&(0,e.jsx)("li",{children:(0,e.jsx)(i,{fullWidth:!0,role:"menuitem",size:"small",onClick:()=>b(null),children:d})}),L.map(s=>(0,e.jsx)("li",{children:(0,e.jsx)(i,{fullWidth:!0,role:"menuitem",size:"small",icon:(0,e.jsx)(N,{size:"md",user:s.user}),onClick:()=>b(s.user),children:(0,e.jsxs)("span",{className:"flex items-center justify-between gap-2 flex-1",children:[(0,e.jsx)("span",{children:m(s.user)}),(0,e.jsx)("span",{className:"text-secondary",children:r[0]===s&&"(you)"})]})})},s.user.uuid)),z?(0,e.jsx)("div",{className:"p-2 text-secondary italic truncate border-t",children:"Loading..."}):L.length===0?(0,e.jsx)("div",{className:"p-2 text-secondary italic truncate border-t",children:y?(0,e.jsx)("span",{children:"No matches"}):(0,e.jsx)("span",{children:"No users"})}):null]})]}),children:f?f(t):(0,e.jsx)(i,{size:"small",type:"secondary",...U,children:t?(0,e.jsxs)("span",{children:[m(t),r[0].user.uuid===t.uuid?" (you)":""]}):d})})}export{j as a};
//# sourceMappingURL=/static/chunk-QNYERZG7.js.map
