import{a as h}from"/static/chunk-YCSVRBIX.js";import{b as B,d as r,f as x,h as E}from"/static/chunk-O3CE2WEF.js";import{d as l,f as A}from"/static/chunk-HRNZBUVG.js";import{Ko as u,Sd as y,Tf as C,a as _,de as b,ee as S,r as f}from"/static/chunk-TW5IU73S.js";import{a as k}from"/static/chunk-3UDJFOQH.js";import{d as i,e as v,g as d,j as g}from"/static/chunk-SJXEOBQC.js";v();g();d();var t=i(_());var s=i(k());var e=i(f());function F(){let{currentTeam:p}=(0,t.useValues)(u),{updateCurrentTeam:L}=(0,t.useActions)(u),{globalSurveyAppearanceConfigAvailable:c}=(0,t.useValues)(B),[T,N]=(0,s.useState)(null),[a,P]=(0,s.useState)(p?.survey_config?.appearance||l),[n,z]=(0,s.useState)(A);n.appearance===l&&(n.appearance=a);let D=()=>{let o=x(a),m={backgroundColor:r(o?.backgroundColor,"background color"),borderColor:r(o?.borderColor,"border color"),ratingButtonActiveColor:r(o?.ratingButtonActiveColor,"rating button active color"),ratingButtonColor:r(o?.ratingButtonColor,"rating button color"),submitButtonColor:r(o?.submitButtonColor,"button color"),submitButtonTextColor:r(o?.submitButtonTextColor,"button text color")},w=Object.values(m).some(V=>V!==void 0);N(m),!(w||!o)&&L({survey_config:{...p?.survey_config,appearance:o}})};return(0,e.jsxs)(e.Fragment,{children:[(0,e.jsxs)("div",{className:"flex items-center gap-2 mb-2",children:[(0,e.jsx)(C.Pure,{className:"mt-2",label:"Appearance",children:(0,e.jsx)("span",{children:"These settings apply to new surveys in this organization."})}),(0,e.jsx)("div",{className:"flex-1"}),c&&(0,e.jsx)(y,{type:"primary",onClick:D,children:"Save settings"})]}),(0,e.jsx)(S,{}),(0,e.jsxs)("div",{className:"flex gap-2 mb-2 align-top",children:[(0,e.jsx)(h,{appearance:a,hasBranchingLogic:!1,customizeRatingButtons:!0,customizePlaceholderText:!0,onAppearanceChange:o=>{P({...a,...o}),z({...n,appearance:o})},validationErrors:T}),(0,e.jsx)("div",{className:"flex-1"}),(0,e.jsx)("div",{className:"mt-10 mr-5 survey-view",children:c&&(0,e.jsx)(E,{survey:n,previewPageIndex:0})})]})]})}function H(){b.open({title:"Surveys settings",content:(0,e.jsx)(F,{}),width:600,primaryButton:{children:"Done"}})}export{F as a,H as b};
//# sourceMappingURL=/static/chunk-R6LTNABA.js.map
