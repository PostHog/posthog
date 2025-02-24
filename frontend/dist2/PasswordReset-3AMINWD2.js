import{a as s}from"/static/chunk-YYJAAGNV.js";import{a as L}from"/static/chunk-YZBUF2ID.js";import{a as R}from"/static/chunk-R6SH42VN.js";import"/static/chunk-YLWX37ZH.js";import"/static/chunk-DXU2OWVA.js";import{$a as P,Oe as b,Qd as v,Sd as i,Ta as g,Tf as S,a as N,af as x,da as f,ee as y,f as E,ie as w,r as p,tb as h}from"/static/chunk-RFJTZKD6.js";import"/static/chunk-XPJ4MQJV.js";import"/static/chunk-3UDJFOQH.js";import"/static/chunk-HHT4SG7V.js";import"/static/chunk-K7LQKAJG.js";import"/static/chunk-QQTK3LZH.js";import"/static/chunk-IJQNM355.js";import"/static/chunk-4CN6THWS.js";import"/static/chunk-272RTCFX.js";import"/static/chunk-2ROB4QWU.js";import"/static/chunk-ALT2ZZSO.js";import"/static/chunk-UE6SLBBN.js";import"/static/chunk-GINZUAUY.js";import"/static/chunk-SQELCOUW.js";import"/static/chunk-IGYUTZ65.js";import"/static/chunk-YM6UBNGD.js";import"/static/chunk-C6TQ5FFZ.js";import"/static/chunk-GXGA523B.js";import"/static/chunk-N4MMWRNK.js";import"/static/chunk-NRLAI7OY.js";import"/static/chunk-LVVHNICT.js";import"/static/chunk-2AXSSSSX.js";import"/static/chunk-DGXQI7RB.js";import"/static/chunk-HUCRWDLX.js";import"/static/chunk-RFEQG3YN.js";import"/static/chunk-PUISI233.js";import{d as r,e as c,g as d,j as u}from"/static/chunk-SJXEOBQC.js";c();u();d();var t=r(N()),k=r(P()),n=r(E());var e=r(p()),H={component:B,logic:s};function B(){let{preflight:o,preflightLoading:a}=(0,t.useValues)(x),{requestPasswordResetSucceeded:l,requestPasswordResetManualErrors:m}=(0,t.useValues)(s);return(0,e.jsxs)(R,{view:"password-reset",footer:(0,e.jsx)(L,{}),children:[m?.code==="throttled"?(0,e.jsx)("div",{className:"text-center ",children:(0,e.jsx)(f,{className:"text-5xl text-danger"})}):l&&(0,e.jsx)("div",{className:"text-center",children:(0,e.jsx)(h,{className:"text-5xl text-success"})}),(0,e.jsx)("h2",{children:"Reset password"}),a?(0,e.jsx)(v,{}):o?.email_service_available?m?.code==="throttled"?(0,e.jsx)(I,{}):l?(0,e.jsx)(F,{}):(0,e.jsx)(C,{}):(0,e.jsx)(q,{})]})}function q(){return(0,e.jsxs)("div",{children:[(0,e.jsxs)("div",{children:["Self-serve password reset is unavailable. Please ",(0,e.jsx)("b",{children:"contact your instance administrator"})," to reset your password."]}),(0,e.jsx)(y,{className:"my-6"}),(0,e.jsxs)("div",{className:"mt-4",children:["If you're an administrator:",(0,e.jsx)("p",{children:(0,e.jsxs)("ul",{children:[(0,e.jsxs)("li",{children:["Password reset is unavailable because email service is not configured."," ",(0,e.jsx)(g,{to:"https://posthog.com/docs/self-host/configure/email?utm_medium=in-product&utm_campaign=password-reset",children:"Read the docs"})," ","on how to set this up."]}),(0,e.jsx)("li",{children:"To reset the password manually, run the following command in your instance."})]})}),(0,e.jsx)(b,{language:"bash",wrap:!0,children:"python manage.py changepassword [account email]"})]})]})}function C(){let{isRequestPasswordResetSubmitting:o}=(0,t.useValues)(s);return(0,e.jsxs)(k.Form,{logic:s,formKey:"requestPasswordReset",className:"space-y-4",enableFormOnSubmit:!0,children:[(0,e.jsx)("div",{className:"text-center",children:"Enter your email address. If an account exists, you\u2019ll receive an email with a password reset link soon."}),(0,e.jsx)(S,{name:"email",label:"Email",children:(0,e.jsx)(w,{className:"ph-ignore-input",autoFocus:!0,"data-attr":"reset-email",placeholder:"email@yourcompany.com",type:"email",disabled:o})}),(0,e.jsx)(i,{fullWidth:!0,type:"primary",status:"alt",center:!0,htmlType:"submit","data-attr":"password-reset",loading:o,size:"large",children:"Continue"})]})}function F(){let{requestPasswordReset:o}=(0,t.useValues)(s),{push:a}=(0,t.useActions)(n.router);return(0,e.jsxs)("div",{className:"text-center",children:["Request received successfully! If the email ",(0,e.jsx)("b",{children:o?.email||"you typed"})," exists, you\u2019ll receive an email with a reset link soon.",(0,e.jsx)("div",{className:"mt-4",children:(0,e.jsx)(i,{type:"primary",status:"alt","data-attr":"back-to-login",center:!0,fullWidth:!0,onClick:()=>a("/login"),size:"large",children:"Back to login"})})]})}function I(){let{requestPasswordReset:o}=(0,t.useValues)(s),{push:a}=(0,t.useActions)(n.router);return(0,e.jsxs)("div",{className:"text-center",children:["There have been too many reset requests for the email ",(0,e.jsx)("b",{children:o?.email||"you typed"}),". Please try again later or contact support if you think this has been a mistake.",(0,e.jsx)("div",{className:"mt-4",children:(0,e.jsx)(i,{type:"primary",status:"alt","data-attr":"back-to-login",center:!0,fullWidth:!0,onClick:()=>a("/login"),size:"large",children:"Back to login"})})]})}export{B as PasswordReset,H as scene};
//# sourceMappingURL=/static/PasswordReset-3AMINWD2.js.map
