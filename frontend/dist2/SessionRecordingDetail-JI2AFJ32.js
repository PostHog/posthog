import{Do as n,Hm as V,Ko as Z,Ta as b,Wd as W,a,lo as S,m as d,r as g,vo as N}from"/static/chunk-TW5IU73S.js";import"/static/chunk-XPJ4MQJV.js";import{F as t}from"/static/chunk-3UDJFOQH.js";import"/static/chunk-HHT4SG7V.js";import"/static/chunk-K7LQKAJG.js";import"/static/chunk-QQTK3LZH.js";import"/static/chunk-IJQNM355.js";import"/static/chunk-4CN6THWS.js";import"/static/chunk-272RTCFX.js";import"/static/chunk-2ROB4QWU.js";import"/static/chunk-ALT2ZZSO.js";import"/static/chunk-UE6SLBBN.js";import"/static/chunk-GINZUAUY.js";import"/static/chunk-SQELCOUW.js";import"/static/chunk-IGYUTZ65.js";import"/static/chunk-YM6UBNGD.js";import"/static/chunk-C6TQ5FFZ.js";import"/static/chunk-GXGA523B.js";import"/static/chunk-N4MMWRNK.js";import"/static/chunk-NRLAI7OY.js";import"/static/chunk-LVVHNICT.js";import"/static/chunk-2AXSSSSX.js";import"/static/chunk-DGXQI7RB.js";import"/static/chunk-HUCRWDLX.js";import"/static/chunk-RFEQG3YN.js";import"/static/chunk-PUISI233.js";import{d as s,e as c,g as p,j as m}from"/static/chunk-SJXEOBQC.js";c();m();p();var l=s(a());c();m();p();var i=s(a());var y=(0,i.kea)([(0,i.path)(["scenes","session-recordings","detail","sessionRecordingDetailLogic"]),(0,i.props)({}),(0,i.selectors)({breadcrumbs:[()=>[(e,r)=>r.id],e=>[{key:"Replay",name:"Replay",path:n.replay()},{key:["ReplaySingle",e],name:e??"Not Found",path:e?n.replaySingle(e):void 0}]]})]);var o=s(g()),O={logic:y,component:T,paramsToProps:({params:{id:e}})=>({id:e})};function T({id:e}={}){let{currentTeam:r}=(0,l.useValues)(Z),{featureFlags:R}=(0,l.useValues)(d),u=R[t.ENVIRONMENTS]?"environment":"project";return(0,o.jsxs)("div",{className:"SessionRecordingScene",children:[(0,o.jsx)(N,{}),r&&!r?.session_recording_opt_in?(0,o.jsx)("div",{className:"mb-4",children:(0,o.jsxs)(W,{type:"info",children:["Session recordings are currently disabled for this ",u,". To use this feature, please go to your ",(0,o.jsx)(b,{to:`${n.settings("project")}#recordings`,children:"project settings"})," and enable it."]})}):null,(0,o.jsx)("div",{className:"mt-4 flex-1",children:e?(0,o.jsx)(S,{sessionRecordingId:e,playerKey:`${e}-detail`}):(0,o.jsx)(V,{})})]})}export{T as SessionRecordingDetail,O as scene};
//# sourceMappingURL=/static/SessionRecordingDetail-JI2AFJ32.js.map
