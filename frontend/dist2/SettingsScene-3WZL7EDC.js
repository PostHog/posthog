import{b as p,c as I}from"/static/chunk-COOXGJAW.js";import"/static/chunk-TKAGNC63.js";import"/static/chunk-YYWKS7VJ.js";import"/static/chunk-DKBGYLEK.js";import"/static/chunk-ZH744EYW.js";import"/static/chunk-QWUPOSXD.js";import"/static/chunk-NEPY3GOZ.js";import"/static/chunk-NDVJEFKZ.js";import"/static/chunk-TUL3J7MM.js";import"/static/chunk-R6LTNABA.js";import"/static/chunk-DT27PZCF.js";import"/static/chunk-YCSVRBIX.js";import"/static/chunk-O3CE2WEF.js";import"/static/chunk-5QZ3UKWA.js";import"/static/chunk-QUCOEN55.js";import"/static/chunk-G6Q3YRDS.js";import"/static/chunk-YHRI2AZY.js";import"/static/chunk-K6PZB6NF.js";import"/static/chunk-TIKFJXRT.js";import"/static/chunk-KYJ4OXJI.js";import"/static/chunk-KYV72GAC.js";import"/static/chunk-OXUIEO32.js";import"/static/chunk-SEJ4C6TB.js";import"/static/chunk-AZNOCCXL.js";import"/static/chunk-KRWBS22W.js";import"/static/chunk-OFFTP67N.js";import"/static/chunk-Q2TQBXTL.js";import"/static/chunk-WTEAZEML.js";import"/static/chunk-TBYU2GKH.js";import"/static/chunk-WNE4BY7V.js";import"/static/chunk-DJ5KSU5H.js";import"/static/chunk-QNYERZG7.js";import"/static/chunk-HRNZBUVG.js";import"/static/chunk-Y35PDO57.js";import"/static/chunk-CEZSENEJ.js";import{Do as c,Fe as b,a as S,f,m as h,r as L}from"/static/chunk-TW5IU73S.js";import"/static/chunk-XPJ4MQJV.js";import{F as y,Ha as v,a as w}from"/static/chunk-3UDJFOQH.js";import"/static/chunk-HHT4SG7V.js";import"/static/chunk-K7LQKAJG.js";import"/static/chunk-QQTK3LZH.js";import"/static/chunk-IJQNM355.js";import"/static/chunk-4CN6THWS.js";import"/static/chunk-272RTCFX.js";import"/static/chunk-2ROB4QWU.js";import"/static/chunk-ALT2ZZSO.js";import"/static/chunk-UE6SLBBN.js";import"/static/chunk-GINZUAUY.js";import"/static/chunk-SQELCOUW.js";import"/static/chunk-IGYUTZ65.js";import"/static/chunk-YM6UBNGD.js";import"/static/chunk-C6TQ5FFZ.js";import"/static/chunk-GXGA523B.js";import"/static/chunk-N4MMWRNK.js";import"/static/chunk-NRLAI7OY.js";import"/static/chunk-LVVHNICT.js";import"/static/chunk-2AXSSSSX.js";import"/static/chunk-DGXQI7RB.js";import"/static/chunk-HUCRWDLX.js";import"/static/chunk-RFEQG3YN.js";import"/static/chunk-PUISI233.js";import{d as l,e as i,g as a,j as s}from"/static/chunk-SJXEOBQC.js";i();s();a();var k=l(S()),j=l(f());i();s();a();var z=l(w());function F(e){(0,z.useEffect)(()=>{e&&document.getElementById(e.slice(1))&&setTimeout(()=>{let t=document.getElementById(e.slice(1));t&&(t.classList.add("highlighted"),t.scrollIntoView())},1e3/60)},[e])}i();s();a();var o=l(S()),r=l(f());i();s();a();var E=["environment","project","organization","user"];var T=(0,o.kea)([(0,o.path)(["scenes","settings","settingsSceneLogic"]),(0,o.connect)(()=>({values:[h,["featureFlags"],p({logicKey:"settingsScene"}),["selectedLevel","selectedSectionId","sections","settings","sections"]],actions:[p({logicKey:"settingsScene"}),["selectLevel","selectSection","selectSetting"]]})),(0,o.selectors)({breadcrumbs:[e=>[e.selectedLevel,e.selectedSectionId,e.sections],(e,t,n)=>[{key:"Settings",name:"Settings",path:c.settings("project")},{key:["Settings",t||e],name:t?n.find(g=>g.id===t)?.title:v(e)}]]}),(0,o.listeners)(({values:e})=>({async selectSetting({setting:t}){let n=c.absolute(c.currentProject(c.settings(e.selectedSectionId??e.selectedLevel,t)));await b(n)}})),(0,r.urlToAction)(({actions:e,values:t})=>({"/settings/:section":({section:n})=>{n&&(!n.endsWith("-details")&&!n.endsWith("-danger-zone")&&(t.featureFlags[y.ENVIRONMENTS]?n=n.replace(/^project/,"environment"):n=n.replace(/^environment/,"project")),E.includes(n)?(n!==t.selectedLevel||t.selectedSectionId)&&e.selectLevel(n):n!==t.selectedSectionId&&e.selectSection(n,t.sections.find(g=>g.id===n)?.level||"user"))}})),(0,r.actionToUrl)(({values:e})=>({selectLevel({level:t}){return[c.settings(t),r.router.values.searchParams,r.router.values.hashParams,{replace:!0}]},selectSection({section:t}){return[c.settings(t),r.router.values.searchParams,r.router.values.hashParams,{replace:!0}]},selectSetting({setting:t}){return[c.settings(e.selectedSectionId??e.selectedLevel,t),void 0,void 0,{replace:!0}]}}))]);var x=l(L()),ie={component:A,logic:T};function A(){let{location:e}=(0,k.useValues)(j.router);return F(e.hash),(0,x.jsx)(I,{logicKey:"settingsScene",handleLocally:!0})}export{A as SettingsScene,ie as scene};
//# sourceMappingURL=/static/SettingsScene-3WZL7EDC.js.map
