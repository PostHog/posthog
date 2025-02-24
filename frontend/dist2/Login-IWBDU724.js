import{a as F}from"/static/chunk-P6PC2ZQE.js";import{a as v}from"/static/chunk-NYXBDRW2.js";import{a as Y}from"/static/chunk-6RTFPWQZ.js";import{$a as Q,Ho as y,Mp as m,Sd as N,Ta as l,Tf as w,Vd as W,Wd as Z,a as x,af as L,h as X,ie as I,r as S,ym as J,zm as R}from"/static/chunk-TW5IU73S.js";import"/static/chunk-XPJ4MQJV.js";import{Z as f,a as C}from"/static/chunk-3UDJFOQH.js";import"/static/chunk-HHT4SG7V.js";import"/static/chunk-K7LQKAJG.js";import"/static/chunk-QQTK3LZH.js";import"/static/chunk-IJQNM355.js";import"/static/chunk-4CN6THWS.js";import"/static/chunk-272RTCFX.js";import"/static/chunk-2ROB4QWU.js";import"/static/chunk-ALT2ZZSO.js";import"/static/chunk-UE6SLBBN.js";import"/static/chunk-GINZUAUY.js";import"/static/chunk-SQELCOUW.js";import"/static/chunk-IGYUTZ65.js";import"/static/chunk-YM6UBNGD.js";import"/static/chunk-C6TQ5FFZ.js";import"/static/chunk-GXGA523B.js";import"/static/chunk-N4MMWRNK.js";import"/static/chunk-NRLAI7OY.js";import"/static/chunk-LVVHNICT.js";import"/static/chunk-2AXSSSSX.js";import"/static/chunk-DGXQI7RB.js";import"/static/chunk-HUCRWDLX.js";import"/static/chunk-RFEQG3YN.js";import"/static/chunk-PUISI233.js";import{d as a,e as g,g as h,j as b}from"/static/chunk-SJXEOBQC.js";g();b();h();var U=a(X()),d=a(x()),B=a(Q());var p=a(C());g();b();h();var H="ph_current_instance",j=2500;function T(t){try{let e=t?.replace(/"/g,"");if(!e)return null;switch(new URL(e).hostname){case"eu.posthog.com":return"eu";case"us.posthog.com":return"us";default:return null}}catch(e){return f(e,{extra:{loggedInInstance:t}}),null}}function D(t){switch(t){case"us":return"US";case"eu":return"EU"}}function E(){let t=window.location.hostname.split(".")[0],e=y(H),n=T(e);if(!n)return;if(n!==t){let s=new URL(window.location.href);s.hostname=s.hostname.replace(t,n);let i=!1,c=()=>{i||window.location.assign(s.href)};W.info(`Redirecting to your logged-in account in the Cloud ${D(n)} region`,{button:{label:"Cancel",action:()=>{i=!0}},onClose:c,closeButton:!1,autoClose:j})}}var o=a(S()),A={no_new_organizations:"Your email address is not associated with an account. Please ask your administrator for an invite.",invalid_sso_provider:(0,o.jsxs)(o.Fragment,{children:["The SSO provider you specified is invalid. Visit"," ",(0,o.jsx)(l,{to:"https://posthog.com/sso",target:"_blank",children:"https://posthog.com/sso"})," ","for details."]}),improperly_configured_sso:(0,o.jsxs)(o.Fragment,{children:["Cannot login with SSO provider because the provider is not configured, or your instance does not have the required license. Please visit"," ",(0,o.jsx)(l,{to:"https://posthog.com/sso",target:"_blank",children:"https://posthog.com/sso"})," ","for details."]}),jit_not_enabled:"We could not find an account with your email address and your organization does not support automatic enrollment. Please contact your administrator for an invite."},Vo={component:_,logic:m};function _(){let{precheck:t}=(0,d.useActions)(m),{precheckResponse:e,precheckResponseLoading:n,login:r,isLoginSubmitting:s,generalError:i}=(0,d.useValues)(m),{preflight:c}=(0,d.useValues)(L),V=(0,p.useRef)(null),u=e.status==="pending"||e.sso_enforcement;return(0,p.useEffect)(()=>{if(c?.cloud)try{E()}catch(G){f(G)}},[]),(0,p.useEffect)(()=>{u||V.current?.focus()},[u]),(0,o.jsx)(Y,{view:"login",hedgehog:!0,message:(0,o.jsxs)(o.Fragment,{children:["Welcome to",(0,o.jsx)("br",{})," PostHog",c?.cloud?" Cloud":"","!"]}),footer:(0,o.jsx)(v,{}),children:(0,o.jsxs)("div",{className:"space-y-4",children:[(0,o.jsx)("h2",{children:"Log in"}),i&&(0,o.jsx)(Z,{type:"error",children:i.detail||A[i.code]||(0,o.jsxs)(o.Fragment,{children:["Could not complete your login.",(0,o.jsx)("br",{}),"Please try again."]})}),(0,o.jsxs)(B.Form,{logic:m,formKey:"login",enableFormOnSubmit:!0,className:"space-y-4",children:[(0,o.jsx)(F,{}),(0,o.jsx)(w,{name:"email",label:"Email",children:(0,o.jsx)(I,{className:"ph-ignore-input",autoFocus:!0,"data-attr":"login-email",placeholder:"email@yourcompany.com",type:"email",onBlur:()=>t({email:r.email}),onPressEnter:G=>{t({email:r.email}),u&&(G.preventDefault(),V.current?.focus())}})}),(0,o.jsx)("div",{className:(0,U.default)("PasswordWrapper",u&&"zero-height"),children:(0,o.jsx)(w,{name:"password",label:(0,o.jsxs)("div",{className:"flex flex-1 items-center justify-between gap-2",children:[(0,o.jsx)("span",{children:"Password"}),(0,o.jsx)(l,{to:"/reset","data-attr":"forgot-password",children:"Forgot your password?"})]}),children:(0,o.jsx)(I,{type:"password",inputRef:V,className:"ph-ignore-input","data-attr":"password",placeholder:"\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022",autoComplete:"current-password"})})}),!e.sso_enforcement&&(0,o.jsx)(N,{type:"primary",status:"alt",htmlType:"submit","data-attr":"password-login",fullWidth:!0,center:!0,loading:s||n,size:"large",children:"Log in"}),e.sso_enforcement&&(0,o.jsx)(R,{provider:e.sso_enforcement,email:r.email}),e.saml_available&&!e.sso_enforcement&&(0,o.jsx)(R,{provider:"saml",email:r.email})]}),c?.cloud&&(0,o.jsxs)("div",{className:"text-center mt-4",children:["Don't have an account?"," ",(0,o.jsx)(l,{to:"/signup","data-attr":"signup",className:"font-bold",children:"Create an account"})]}),!e.saml_available&&!e.sso_enforcement&&(0,o.jsx)(J,{caption:"Or log in with",topDivider:!0})]})})}export{A as ERROR_MESSAGES,_ as Login,Vo as scene};
//# sourceMappingURL=/static/Login-IWBDU724.js.map
