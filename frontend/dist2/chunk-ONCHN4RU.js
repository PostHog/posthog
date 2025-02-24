import{Od as r,fe as s,r as l}from"/static/chunk-TW5IU73S.js";import{d as o,e as a,g as p,j as d}from"/static/chunk-SJXEOBQC.js";a();d();p();var e=o(l()),y={1:{tagType:"success",display:"Active",description:(0,e.jsx)(e.Fragment,{children:"The function is running as expected."})},2:{tagType:"caution",display:"Degraded",description:(0,e.jsx)(e.Fragment,{children:"The function is running slow or has issues performing async requests. It has been moved to the slow lane and may be processing slower than usual."})},3:{tagType:"danger",display:"Disabled temporarily",description:(0,e.jsx)(e.Fragment,{children:"The function has been disabled temporarily due to enough slow or failed requests. It will be re-enabled soon."})},4:{tagType:"danger",display:"Disabled",description:(0,e.jsx)(e.Fragment,{children:'The function has been disabled indefinitely due to too many slow or failed requests. Please check your config. Updating your function will move it back to the "degraded" state for testing. If it performs well, it will then be moved to the healthy.'})}},g={tagType:"default",display:"Unknown",description:(0,e.jsx)(e.Fragment,{children:"The function status is unknown. The status will be derived once enough invocations have been performed."})},c={tagType:"default",display:"Paused",description:(0,e.jsx)(e.Fragment,{children:"This function is paused"})};function v({hogFunction:t}){if(!t)return null;let{tagType:n,display:i,description:u}=t.type==="site_app"||t.type==="site_destination"?t.enabled?y[1]:c:t.status?.state?y[t.status.state]:t.enabled?g:c;return(0,e.jsx)(r,{overlay:(0,e.jsx)(e.Fragment,{children:(0,e.jsxs)("div",{className:"p-2 space-y-2",children:[(0,e.jsxs)("h2",{className:"flex items-center m-0 gap-2",children:["Function status - ",(0,e.jsx)(s,{type:n,children:i})]}),(0,e.jsx)("p",{children:u})]})}),children:(0,e.jsx)(s,{type:n,children:i})})}export{v as a};
//# sourceMappingURL=/static/chunk-ONCHN4RU.js.map
