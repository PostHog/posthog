import{a as w}from"/static/chunk-R6SH42VN.js";import{a as i}from"/static/chunk-ASGQOEM4.js";import{$d as v,Qd as p,Sd as c,a as E,ce as x,ei as N,ih as g,mh as k,r as y,rh as b}from"/static/chunk-RFJTZKD6.js";import"/static/chunk-XPJ4MQJV.js";import{a as L}from"/static/chunk-3UDJFOQH.js";import"/static/chunk-HHT4SG7V.js";import"/static/chunk-K7LQKAJG.js";import"/static/chunk-QQTK3LZH.js";import"/static/chunk-IJQNM355.js";import"/static/chunk-4CN6THWS.js";import"/static/chunk-272RTCFX.js";import"/static/chunk-2ROB4QWU.js";import"/static/chunk-ALT2ZZSO.js";import"/static/chunk-UE6SLBBN.js";import"/static/chunk-GINZUAUY.js";import"/static/chunk-SQELCOUW.js";import"/static/chunk-IGYUTZ65.js";import"/static/chunk-YM6UBNGD.js";import"/static/chunk-C6TQ5FFZ.js";import"/static/chunk-GXGA523B.js";import"/static/chunk-N4MMWRNK.js";import"/static/chunk-NRLAI7OY.js";import"/static/chunk-LVVHNICT.js";import"/static/chunk-2AXSSSSX.js";import"/static/chunk-DGXQI7RB.js";import"/static/chunk-HUCRWDLX.js";import"/static/chunk-RFEQG3YN.js";import"/static/chunk-PUISI233.js";import{d as m,e as u,g as f,j as h}from"/static/chunk-SJXEOBQC.js";u();h();f();var a=m(E());var d=m(L());var e=m(y()),O={component:V,logic:i},S=({disabledReason:t})=>{let{openSupportForm:s}=(0,a.useActions)(N),{requestVerificationLink:n}=(0,a.useActions)(i),{uuid:r}=(0,a.useValues)(i);return(0,e.jsxs)("div",{className:"flex flex-row gap-x-4 justify-start",children:[(0,e.jsx)(c,{type:"primary",disabledReason:t,onClick:()=>{s({kind:"bug",target_area:"login"})},children:"Contact support"}),r&&(0,e.jsx)(c,{type:"primary",disabledReason:t,onClick:()=>{n(r)},children:"Request a new link"})]})},B=()=>{let[t,s]=(0,d.useState)([]),n=["Wait 5 minutes. Sometimes it takes a bit for email providers to deliver emails.","Check your spam folder and any firewalls you may have active","Ask your company IT department to allow any emails from @posthog.com","Channel your inner hedgehog and take another peek at your inbox"],r=l=>{let o=[...t];o[l]=!o[l],s(o)},C=n.every((l,o)=>t[o]);return(0,e.jsxs)("div",{className:"bg-primary p-4 rounded relative w-full max-w-160",children:[(0,e.jsx)("div",{className:"flex flex-col justify-center",children:(0,e.jsx)("div",{className:"space-y-2 text-left",children:n.map((l,o)=>(0,e.jsx)(v,{onChange:()=>r(o),checked:t[o],label:l,bordered:!0,size:"small"},o))})}),(0,e.jsxs)("div",{className:"mt-4",children:[(0,e.jsx)("p",{className:"text-left mb-2",children:"Choose one of the following options:"}),(0,e.jsx)(S,{disabledReason:C?void 0:"Please confirm you've done all the steps above"})]})]})},H=()=>{let[t,s]=(0,d.useState)(!1);return(0,e.jsxs)(e.Fragment,{children:[(0,e.jsx)(c,{type:"primary",onClick:()=>s(!0),children:"Get help"}),(0,e.jsx)(x,{isOpen:t,onClose:()=>s(!1),title:"Get help",description:(0,e.jsx)("p",{className:"max-w-160",children:"Sorry you're having troubles! We're here to help, but first we ask that you check a few things first on your end. Generally any issues with email happen after they leave our hands."}),children:(0,e.jsx)(B,{})})]})};function V(){let{view:t}=(0,a.useValues)(i);return(0,e.jsx)("div",{className:"flex h-full flex-col",children:(0,e.jsx)("div",{className:"flex h-full",children:(0,e.jsx)(w,{view:"verifyEmail",fixedWidth:!1,children:(0,e.jsx)("div",{className:"px-12 py-8 text-center flex flex-col items-center max-w-160 w-full",children:t==="pending"?(0,e.jsxs)(e.Fragment,{children:[(0,e.jsx)("h2",{className:"text-lg",children:"Welcome to PostHog!"}),(0,e.jsx)("h1",{className:"text-3xl font-bold",children:"Let's verify your email address."}),(0,e.jsx)("div",{className:"max-w-60 my-10",children:(0,e.jsx)(b,{className:"w-full h-full"})}),(0,e.jsx)("p",{className:"mb-6",children:"An email has been sent with a link to verify your email address."}),(0,e.jsx)(H,{})]}):t==="verify"?(0,e.jsxs)(e.Fragment,{children:[(0,e.jsx)(p,{className:"text-4xl mb-12"}),(0,e.jsx)("p",{children:"Verifying your email address..."})]}):t==="success"?(0,e.jsxs)(e.Fragment,{children:[(0,e.jsx)("h1",{className:"text-3xl font-bold",children:"Success!"}),(0,e.jsx)("div",{className:"max-w-60 mb-12",children:(0,e.jsx)(k,{className:"w-full h-full"})}),(0,e.jsx)("p",{children:"Thanks for verifying your email address. Now taking you to PostHog..."})]}):t==="invalid"?(0,e.jsxs)(e.Fragment,{children:[(0,e.jsx)("h1",{className:"text-3xl font-bold",children:"Whoops!"}),(0,e.jsx)("div",{className:"max-w-60 mb-12",children:(0,e.jsx)(g,{className:"w-full h-full"})}),(0,e.jsx)("p",{className:"mb-6",children:"Seems like that link isn't quite right. Try again?"}),(0,e.jsx)(S,{})]}):(0,e.jsx)(p,{className:"text-4xl"})})})})})}export{V as VerifyEmail,B as VerifyEmailHelpLinks,O as scene};
//# sourceMappingURL=/static/VerifyEmail-SPHQ2FT3.js.map
