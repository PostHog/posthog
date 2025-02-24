import{a as ne}from"/static/chunk-P6PC2ZQE.js";import{a as oe}from"/static/chunk-MDHSA7YI.js";import{a as te}from"/static/chunk-VBPFBTFJ.js";import{a as ee}from"/static/chunk-6RTFPWQZ.js";import{a as Z,b as j}from"/static/chunk-YYWKS7VJ.js";import"/static/chunk-QWUPOSXD.js";import{$a as H,Do as q,Eo as F,Io as Q,Lj as K,Rd as X,Sd as y,Ta as S,Tf as P,Vd as Y,Wd as G,a as w,af as u,b as I,eb as M,f as $,ie as b,m as D,r as x,tb as J,ym as W}from"/static/chunk-TW5IU73S.js";import"/static/chunk-XPJ4MQJV.js";import{F as V,N,a as B}from"/static/chunk-3UDJFOQH.js";import"/static/chunk-HHT4SG7V.js";import"/static/chunk-K7LQKAJG.js";import"/static/chunk-QQTK3LZH.js";import"/static/chunk-IJQNM355.js";import"/static/chunk-4CN6THWS.js";import"/static/chunk-272RTCFX.js";import"/static/chunk-2ROB4QWU.js";import"/static/chunk-ALT2ZZSO.js";import"/static/chunk-UE6SLBBN.js";import"/static/chunk-GINZUAUY.js";import"/static/chunk-SQELCOUW.js";import"/static/chunk-IGYUTZ65.js";import"/static/chunk-YM6UBNGD.js";import"/static/chunk-C6TQ5FFZ.js";import"/static/chunk-GXGA523B.js";import"/static/chunk-N4MMWRNK.js";import"/static/chunk-NRLAI7OY.js";import"/static/chunk-LVVHNICT.js";import"/static/chunk-2AXSSSSX.js";import"/static/chunk-DGXQI7RB.js";import"/static/chunk-HUCRWDLX.js";import"/static/chunk-RFEQG3YN.js";import"/static/chunk-PUISI233.js";import{d as i,e as c,g as d,j as g}from"/static/chunk-SJXEOBQC.js";c();g();d();var U=i(w()),ce=i($());c();g();d();var L=i(w());var T=i(B());c();g();d();var O=i(w()),ae=i(H());var R=i(B());c();g();d();var p=i(w()),re=i(H()),ie=i($());var de=/(?:[a-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[a-z0-9!#$%&'*+/=?^_`{|}~-]+)*|"(?:[\x01-\x08\x0b\x0c\x0e-\x1f\x21\x23-\x5b\x5d-\x7f]|\\[\x01-\x09\x0b\x0c\x0e-\x7f])*")@(?:(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]*[a-z0-9])?|\[(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?|[a-z0-9-]*[a-z0-9]:(?:[\x01-\x08\x0b\x0c\x0e-\x1f\x21-\x5a\x53-\x7f]|\\[\x01-\x09\x0b\x0c\x0e-\x7f])+)\])/,f=(0,p.kea)([(0,p.path)(["scenes","authentication","signupLogic"]),(0,p.connect)({values:[u,["preflight"],D,["featureFlags"]]}),(0,p.actions)({setPanel:e=>({panel:e})}),(0,p.reducers)({panel:[0,{setPanel:(e,{panel:n})=>n}]}),(0,re.forms)(({actions:e,values:n})=>({signupPanel1:{alwaysShowErrors:!0,showErrorsOnTouch:!0,defaults:{email:"",password:""},errors:({email:o,password:r})=>({email:o?de.test(o)?void 0:"Please use a valid email address":"Please enter your email to continue",password:n.preflight?.demo?void 0:r?n.validatedPassword.feedback||void 0:"Please enter your password to continue"}),submit:async()=>{e.setPanel(1)}},signupPanel2:{alwaysShowErrors:!0,showErrorsOnTouch:!0,defaults:{name:"",organization_name:"",role_at_organization:"",referral_source:""},errors:({name:o,role_at_organization:r})=>({name:o?void 0:"Please enter your name",role_at_organization:r?void 0:"Please select your role in the organization"}),submit:async(o,r)=>{r();try{let s=await Q.create("api/signup/",{...n.signupPanel1,...o,first_name:o.name.split(" ")[0],last_name:o.name.split(" ")[1]||void 0,organization_name:o.organization_name||void 0});o.organization_name||I.capture("sign up organization name not provided"),location.href=s.redirect_url||"/"}catch(s){throw e.setSignupPanel2ManualErrors({generic:{code:s.code,detail:s.detail}}),s}}}})),(0,p.selectors)({validatedPassword:[e=>[e.signupPanel1],({password:e})=>Z(e)]}),(0,ie.urlToAction)(({actions:e,values:n})=>({"/signup":(o,{email:r,maintenanceRedirect:s})=>{if(n.preflight?.cloud){let h=n.featureFlags[V.REDIRECT_SIGNUPS_TO_INSTANCE],E=["eu","us"],v=K(h)&&E.includes(h),A=n.preflight?.region&&E.includes(n.preflight?.region);v&&A&&h!==n.preflight?.region?.toLowerCase()&&(window.location.href=`https://${N[h.toUpperCase()]}${q.signup()}?maintenanceRedirect=true`),s&&v&&Y.info(`You've been redirected to signup on our ${h.toUpperCase()} instance while we perform maintenance on our other instance.`)}r&&(n.preflight?.demo?(e.setSignupPanel1Values({email:r}),e.setSignupPanel2Values({name:"X",organization_name:"Y"}),e.submitSignupPanel2()):e.setSignupPanel1Value("email",r))}}))]);var a=i(x());function se(){let{preflight:e,socialAuthAvailable:n}=(0,O.useValues)(u),{isSignupPanel1Submitting:o,validatedPassword:r}=(0,O.useValues)(f),s=(0,R.useRef)(null);return(0,R.useEffect)(()=>{s?.current?.focus()},[e?.demo]),(0,a.jsxs)("div",{className:"space-y-4 Signup__panel__1",children:[(0,a.jsx)(ne,{}),!e?.demo&&n&&(0,a.jsxs)(a.Fragment,{children:[(0,a.jsx)(W,{caption:"Sign up with",bottomDivider:!0,className:"mt-6"}),(0,a.jsx)("p",{className:"text-secondary text-center mb-0",children:"Or use email & password"})]}),(0,a.jsxs)(ae.Form,{logic:f,formKey:"signupPanel1",className:"space-y-4",enableFormOnSubmit:!0,children:[(0,a.jsx)(P,{name:"email",label:"Email",children:(0,a.jsx)(b,{className:"ph-ignore-input",autoFocus:!0,"data-attr":"signup-email",placeholder:"email@yourcompany.com",type:"email",inputRef:s,disabled:o})}),!e?.demo&&(0,a.jsx)(P,{name:"password",label:(0,a.jsxs)("div",{className:"flex flex-1 items-center justify-between",children:[(0,a.jsx)("span",{children:"Password"}),(0,a.jsx)(j,{validatedPassword:r})]}),children:(0,a.jsx)(b,{type:"password",autoComplete:"new-password",className:"ph-ignore-input","data-attr":"password",placeholder:"\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022",disabled:o})}),(0,a.jsx)(y,{fullWidth:!0,type:"primary",status:"alt",center:!0,htmlType:"submit","data-attr":"signup-start",loading:o,disabled:o,size:"large",children:"Continue"})]}),!e?.demo&&(e?.cloud||e?.initiated)&&(0,a.jsxs)("div",{className:"text-center mt-4",children:["Already have an account?"," ",(0,a.jsx)(S,{to:"/login","data-attr":"signup-login-link",className:"font-bold",children:"Log in"})]})]})}c();g();d();var _=i(w()),le=i(H());var m=i(x()),me="utm_campaign=in-product&utm_tag=signup-header";function pe(){let{preflight:e}=(0,_.useValues)(u),{setSignupPanel2ManualErrors:n}=(0,_.useActions)(f),{isSignupPanel2Submitting:o}=(0,_.useValues)(f);return(0,m.jsxs)("div",{className:"space-y-4 Signup__panel__2",children:[(0,m.jsxs)(le.Form,{logic:f,formKey:"signupPanel2",className:"space-y-4",enableFormOnSubmit:!0,children:[(0,m.jsx)(P,{name:"name",label:"Your name",children:(0,m.jsx)(b,{className:"ph-ignore-input","data-attr":"signup-name",placeholder:"Jane Doe",disabled:o})}),(0,m.jsx)(P,{name:"organization_name",label:"Organization name",children:(0,m.jsx)(b,{className:"ph-ignore-input","data-attr":"signup-organization-name",placeholder:"Hogflix Movies",disabled:o})}),(0,m.jsx)(te,{}),(0,m.jsx)(oe,{disabled:o}),(0,m.jsx)("div",{className:"divider"}),(0,m.jsx)(y,{fullWidth:!0,type:"primary",center:!0,htmlType:"submit","data-attr":"signup-submit",onClick:()=>n({}),loading:o,disabled:o,status:"alt",size:"large",children:e?.demo?o?"Preparing demo data\u2026":"Enter the demo environment":"Create account"})]}),(0,m.jsxs)("div",{className:"text-center text-secondary",children:["By ",e?.demo?"entering the demo environment":"creating an account",", you agree to our"," ",(0,m.jsx)(S,{to:`https://posthog.com/terms?${me}`,target:"_blank",children:"Terms\xA0of\xA0Service"})," ","and"," ",(0,m.jsx)(S,{to:`https://posthog.com/privacy?${me}`,target:"_blank",children:"Privacy\xA0Policy"}),"."]})]})}var l=i(x());function ue(){let{preflight:e}=(0,L.useValues)(u),{user:n}=(0,L.useValues)(F),{isSignupPanel2Submitting:o,signupPanel2ManualErrors:r,panel:s}=(0,L.useValues)(f),{setPanel:h}=(0,L.useActions)(f),[E,v]=(0,T.useState)(!0);return(0,T.useEffect)(()=>{v(!0);let A=setTimeout(()=>{v(!1)},500);return()=>clearTimeout(A)},[s]),n?null:(0,l.jsxs)("div",{className:"space-y-2",children:[(0,l.jsx)("h2",{children:e?.demo?"Explore PostHog yourself":s===0?"Get started":"Tell us a bit about yourself"}),!o&&r?.generic&&(0,l.jsx)(G,{type:"error",children:r.generic?.detail||"Could not complete your signup. Please try again."}),s===0?(0,l.jsx)(se,{}):(0,l.jsxs)(l.Fragment,{children:[(0,l.jsx)(pe,{}),(0,l.jsx)("div",{className:"flex justify-center",children:(0,l.jsx)(y,{icon:(0,l.jsx)(M,{}),onClick:()=>h(s-1),size:"small",center:!0,"data-attr":"signup-go-back",children:"or go back"})})]}),E?(0,l.jsx)(X,{sceneLevel:!0}):null]})}var t=i(x()),Lo={component:ge};function ge(){let{preflight:e}=(0,U.useValues)(u),{user:n}=(0,U.useValues)(F);return n?null:(0,t.jsx)(ee,{view:"signup",footer:(0,t.jsx)("div",{className:"sm:flex sm:justify-center w-full gap-[10%]",children:{cloud:["Hosted & managed by PostHog","Pay per event, cancel anytime","Fast and reliable support"],selfHosted:["Fully featured product, unlimited events","Data in your own infrastructure","Community forum"]}[e?.cloud?"cloud":"selfHosted"].map((r,s)=>(0,t.jsx)("p",{className:"text-center mb-2",children:r},s))}),sideLogo:!0,leftContainerContent:(0,t.jsx)(he,{}),children:(0,t.jsx)(ue,{})})}var fe=[{benefit:"Free usage every month - even on paid plans",description:"1M free events, 5K free session recordings, and more. Every month. Forever."},{benefit:"Start collecting data immediately",description:"Integrate with developer-friendly APIs or a low-code web snippet."},{benefit:"Join industry leaders that run on PostHog",description:"Airbus, Hasura, Y Combinator, Staples, and thousands more trust PostHog as their Product OS."}];function he(){let{preflight:e}=(0,U.useValues)(u),n=o=>{let{pathname:r,search:s,hash:h}=ce.router.values.currentLocation;return`https://${N[o]}${r}${s}${h}`};return(0,t.jsxs)(t.Fragment,{children:[(0,t.jsx)("div",{className:"mb-16 max-w-100",children:fe.map((o,r)=>(0,t.jsxs)("div",{className:"flex flex-row gap-3 mb-4",children:[(0,t.jsx)("div",{children:(0,t.jsx)(J,{className:"mt-0.5 w-5 h-5 text-link"})}),(0,t.jsxs)("div",{children:[(0,t.jsx)("h3",{className:"mb-1 font-bold leading-6",children:o.benefit}),(0,t.jsx)("p",{className:"m-0 text-sm",children:o.description})]})]},r))}),(0,t.jsxs)("div",{className:"BridgePage__cta border rounded p-4 mt-8 text-center",children:["Did you know?",e?.cloud?(0,t.jsxs)("span",{children:[" ","You can use our"," ",(0,t.jsx)(S,{to:n(e?.region==="EU"?"US":"EU"),children:(0,t.jsxs)("strong",{children:["PostHog Cloud ",e?.region==="EU"?"US":"EU"]})}),e?.region==="EU"?", too":" for a GDPR-ready deployment","."]}):(0,t.jsxs)("span",{children:[" ","You can use our"," ",(0,t.jsx)(S,{to:n("EU"),children:(0,t.jsxs)("strong",{children:["EU"," cloud"]})})," ","or"," ",(0,t.jsx)(S,{to:n("US"),children:(0,t.jsxs)("strong",{children:["US"," cloud"]})})," ","and we'll take care of the hosting for you."]})]})]})}export{ge as SignupContainer,he as SignupLeftContainer,Lo as scene};
//# sourceMappingURL=/static/SignupContainer-OBW5X6WC.js.map
