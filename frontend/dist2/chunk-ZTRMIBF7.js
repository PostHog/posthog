import{Io as n,Vd as a,Za as v,a as y,f as m}from"/static/chunk-TW5IU73S.js";import{d as s,e as l,g as u,j as c}from"/static/chunk-SJXEOBQC.js";l();c();u();var r=s(y()),d=s(v()),f=s(m());var h=(0,r.kea)([(0,r.path)(["scenes","authentication","verifyEmailLogic"]),(0,r.actions)({setView:e=>({view:e}),setUuid:e=>({uuid:e}),requestVerificationLink:e=>({uuid:e}),validateEmailTokenSuccess:e=>({response:e})}),(0,d.loaders)(({actions:e})=>({validatedEmailToken:[null,{validateEmailToken:async({uuid:i,token:t},p)=>{try{return await n.create("api/users/verify_email/",{token:t,uuid:i}),e.setView("success"),await p(2e3),window.location.href="/",{success:!0,token:t,uuid:i}}catch(o){return e.setView("invalid"),{success:!1,errorCode:o.code,errorDetail:o.detail}}}}],newlyRequestedVerificationLink:[null,{requestVerificationLink:async({uuid:i})=>{try{return await n.create("api/users/request_email_verification/",{uuid:i}),a.success("A new verification link has been sent to the associated email address. Please check your inbox."),!0}catch(t){return t.code==="throttled"?(a.error("You have requested a new verification link too many times. Please try again later."),!1):(a.error("Requesting verification link failed. Please try again later or contact support."),!1)}}}]})),(0,r.reducers)({view:[null,{setView:(e,{view:i})=>i}],uuid:[null,{setUuid:(e,{uuid:i})=>i}]}),(0,f.urlToAction)(({actions:e})=>({"/verify_email/:uuid":({uuid:i})=>{i&&(e.setUuid(i),e.setView("pending"))},"/verify_email/:uuid/:token":({uuid:i,token:t})=>{t&&i&&(e.setUuid(i),e.setView("verify"),e.validateEmailToken({uuid:i,token:t}))},"/verify_email":()=>{e.setView("invalid")}}))]);export{h as a};
//# sourceMappingURL=/static/chunk-ZTRMIBF7.js.map
