import{a as W,c as L}from"/static/chunk-LNKKHMEJ.js";import{b as y}from"/static/chunk-WZKEGFTL.js";import{a as A,b as E}from"/static/chunk-JNQTMPE2.js";import{a as T,b as k,c as x}from"/static/chunk-IF5PCV5K.js";import"/static/chunk-LZ4U35M5.js";import{d as H}from"/static/chunk-Y4WAEGNO.js";import"/static/chunk-5QZ3UKWA.js";import"/static/chunk-L6OS4YDC.js";import"/static/chunk-N2KORDXB.js";import"/static/chunk-A5MOAJQD.js";import"/static/chunk-SSCAQKOK.js";import"/static/chunk-G6Q3YRDS.js";import"/static/chunk-XW2JOKCQ.js";import"/static/chunk-CDTERFC5.js";import"/static/chunk-LZWHW4MC.js";import"/static/chunk-RSTRTBMR.js";import"/static/chunk-DYVMG6MY.js";import"/static/chunk-44P5EQSU.js";import"/static/chunk-GH3IWF3M.js";import"/static/chunk-CBJ7RAUW.js";import"/static/chunk-XSEDUXPL.js";import"/static/chunk-HRNZBUVG.js";import"/static/chunk-OKGJSIGC.js";import"/static/chunk-NKVVAJQ7.js";import"/static/chunk-2HTNY362.js";import"/static/chunk-S27Q4QO6.js";import"/static/chunk-JUFFFVO5.js";import"/static/chunk-JZCOVRBI.js";import"/static/chunk-EIJECEWK.js";import{Do as s,Eh as V,Ip as Y,Ka as U,Sd as c,Ta as N,Yi as C,a as Z,ac as Q,bf as X,cg as J,ee as u,h as _,m as h,mh as B,r as b,se as F,vo as S}from"/static/chunk-RFJTZKD6.js";import"/static/chunk-XPJ4MQJV.js";import"/static/chunk-KQJ3FYBQ.js";import{F as I,a as P,na as R}from"/static/chunk-3UDJFOQH.js";import"/static/chunk-HHT4SG7V.js";import"/static/chunk-K7LQKAJG.js";import"/static/chunk-QQTK3LZH.js";import"/static/chunk-IJQNM355.js";import"/static/chunk-4CN6THWS.js";import"/static/chunk-272RTCFX.js";import"/static/chunk-2ROB4QWU.js";import"/static/chunk-ALT2ZZSO.js";import"/static/chunk-UE6SLBBN.js";import"/static/chunk-GINZUAUY.js";import"/static/chunk-SQELCOUW.js";import"/static/chunk-IGYUTZ65.js";import"/static/chunk-YM6UBNGD.js";import"/static/chunk-C6TQ5FFZ.js";import"/static/chunk-GXGA523B.js";import"/static/chunk-N4MMWRNK.js";import"/static/chunk-NRLAI7OY.js";import"/static/chunk-LVVHNICT.js";import"/static/chunk-2AXSSSSX.js";import"/static/chunk-DGXQI7RB.js";import"/static/chunk-HUCRWDLX.js";import"/static/chunk-RFEQG3YN.js";import"/static/chunk-PUISI233.js";import{d as i,e as m,g as d,j as r}from"/static/chunk-SJXEOBQC.js";m();r();d();var a=i(Z());m();r();d();var z=i(_());var w=i(P()),n=i(b());function O({url:e}){let[t,l]=(0,w.useState)(null);return e?(0,n.jsxs)("div",{className:"relative",children:[(0,n.jsx)(B,{width:"36",height:"36",className:(0,z.default)("CheekyHog",t&&"CheekyHog--peek",t===!1&&"CheekyHog--hide")}),(0,n.jsx)("div",{className:"absolute top-0 left-0 w-full h-full YearInHog__mask"}),(0,n.jsx)(c,{icon:(0,n.jsx)(U,{}),type:"secondary",to:e,targetBlank:!0,size:"small",onMouseEnter:()=>l(!0),onMouseLeave:()=>l(!1),children:"PostHog Unwrapped"})]}):null}m();r();d();var p=i(Z());var g=i(b());function K({person:e}){let{reportPersonOpenedFromNewlySeenPersonsList:t}=(0,p.useActions)(Y);return(0,g.jsx)(E,{to:s.personByDistinctId(e.distinct_ids[0]),title:V(e),subtitle:`First seen ${(0,R.default)(e.created_at).fromNow()}`,prefix:(0,g.jsx)(C,{name:V(e)}),onClick:()=>{t()}})}function v(){let{persons:e,personsLoading:t}=(0,p.useValues)(W);return(0,g.jsx)(A,{title:"Newly seen people",viewAllURL:s.persons(),loading:t,emptyMessage:{title:"There are no newly seen people",description:"Learn more about identifying people and ingesting data in the documentation.",buttonText:"Documentation",buttonTo:"https://posthog.com/docs/product-analytics/identify"},items:e.slice(0,5),renderRow:(l,G)=>(0,g.jsx)(K,{person:l},G)})}var o=i(b()),Ko={component:q,logic:W};function q(){let{dashboardLogicProps:e}=(0,a.useValues)(W),{showInviteModal:t}=(0,a.useActions)(X),{showSceneDashboardChoiceModal:l}=(0,a.useActions)(T({scene:"ProjectHomepage"})),{featureFlags:G}=(0,a.useValues)(h),j=(0,o.jsxs)(o.Fragment,{children:[!!G[I.YEAR_IN_HOG]&&window.POSTHOG_APP_CONTEXT?.year_in_hog_url&&(0,o.jsx)(O,{url:`${window.location.origin}${window.POSTHOG_APP_CONTEXT.year_in_hog_url}`}),(0,o.jsx)(c,{type:"secondary",size:"small","data-attr":"project-home-customize-homepage",onClick:l,children:"Customize homepage"}),(0,o.jsx)(c,{"data-attr":"project-home-invite-team-members",onClick:()=>{t()},type:"secondary",children:"Invite members"})]});return(0,o.jsxs)("div",{className:"ProjectHomepage",children:[(0,o.jsx)(S,{delimited:!0,buttons:j}),(0,o.jsxs)("div",{className:"ProjectHomepage__lists",children:[(0,o.jsx)(L,{}),(0,o.jsx)(v,{}),(0,o.jsx)(y,{})]}),e?(0,o.jsx)($,{dashboardLogicProps:e}):(0,o.jsx)(x,{open:()=>{l()},scene:"ProjectHomepage"}),(0,o.jsx)(k,{scene:"ProjectHomepage"})]})}function $({dashboardLogicProps:e}){let{dashboard:t}=(0,a.useValues)(J(e));return(0,o.jsxs)(o.Fragment,{children:[(0,o.jsx)("div",{className:"ProjectHomepage__dashboardheader",children:(0,o.jsxs)("div",{className:"ProjectHomepage__dashboardheader__title",children:[!t&&(0,o.jsx)(F,{className:"w-20 h-4"}),t?.name&&(0,o.jsx)(o.Fragment,{children:(0,o.jsxs)(N,{className:"font-semibold text-xl text-text-3000",to:s.dashboard(t.id),children:[(0,o.jsx)(Q,{className:"mr-2 text-2xl opacity-50"}),t?.name]})})]})}),(0,o.jsx)(u,{className:"mt-3 mb-4"}),(0,o.jsx)(H,{id:e.id.toString(),placement:"project-homepage"})]})}export{q as ProjectHomepage,Ko as scene};
//# sourceMappingURL=/static/ProjectHomepage-TYDW4STT.js.map
