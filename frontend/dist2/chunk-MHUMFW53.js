import{a as k,b as W}from"/static/chunk-I3JBH3PJ.js";import{b as y,c as w}from"/static/chunk-X3DMY2SE.js";import{a as R}from"/static/chunk-N2KORDXB.js";import{a as x}from"/static/chunk-KHKNIVWH.js";import{Ko as A,Qd as H,a as E,b as g,fe as X,h as S,r as _}from"/static/chunk-RFJTZKD6.js";import{Xa as M,a as P,fa as C}from"/static/chunk-3UDJFOQH.js";import{d as c,e as b,g as u,j as h}from"/static/chunk-SJXEOBQC.js";b();h();u();var v=c(S()),f=c(E());b();h();u();var F=c(S());var D=c(P()),T=c(_());function G({src:e,alt:a,index:r,className:t="",imageClassName:o=""}){let[s,m]=(0,D.useState)(!1),d=()=>{m(!0)};return(0,T.jsx)(T.Fragment,{children:s||!e?(0,T.jsx)("div",{className:(0,F.default)("w-full h-full",t),style:{background:C(r)}}):(0,T.jsx)("img",{className:(0,F.default)("object-cover w-full",o),src:e,alt:a,onError:d})})}var O="/static/assets/blank-dashboard-hog-HUPMPIWZ.png";var J=c(P());var n=c(_());function Ve({scope:e="default",onItemClick:a,redirectAfterCreation:r=!0,availabilityContexts:t}){let o=R({scope:e}),{allTemplates:s,allTemplatesLoading:m}=(0,f.useValues)(o),{isLoading:d,newDashboardModalVisible:I}=(0,f.useValues)(x),{setActiveDashboardTemplate:Q,createDashboardFromTemplate:j,addDashboard:q,setIsLoading:L,showVariableSelectModal:K}=(0,f.useActions)(x);return(0,n.jsx)("div",{children:(0,n.jsxs)("div",{className:"DashboardTemplateChooser",children:[!t||t.includes("general")?(0,n.jsx)(Z,{template:{template_name:"Blank dashboard",dashboard_description:"Create a blank dashboard",image_url:O},onClick:()=>{d||(L(!0),q({name:"New Dashboard",show:!0}))},index:0,"data-attr":"create-dashboard-blank"}):null,m?(0,n.jsx)(H,{className:"text-6xl"}):s.filter(p=>t?t.some(V=>p.availability_contexts?.includes(V)):!0).map((p,V)=>(0,n.jsx)(Z,{template:p,onClick:()=>{d||(L(!0),(p.variables||[]).length===0?(p.variables===null&&(p.variables=[]),j(p,p.variables||[],r)):I?Q(p):K(p),a?.(p))},index:V+1,"data-attr":"create-dashboard-from-template"},V))]})})}function Z({template:e,onClick:a,index:r,"data-attr":t}){let[o,s]=(0,J.useState)(!1);return(0,n.jsxs)("div",{className:"cursor-pointer border rounded TemplateItem flex flex-col transition-all",onClick:a,onMouseEnter:()=>s(!0),onMouseLeave:()=>s(!1),"data-attr":t,children:[(0,n.jsx)("div",{className:(0,v.default)("transition-all w-full overflow-hidden",o?"h-4 min-h-4":"h-30 min-h-30"),children:(0,n.jsx)(G,{src:e?.image_url,alt:"cover photo",index:r,imageClassName:"h-30"})}),(0,n.jsx)("h5",{className:"px-2 mb-1",children:e?.template_name}),(0,n.jsx)("div",{className:"flex gap-x-1 px-2 mb-1",children:e.tags?.map((m,d)=>(0,n.jsx)(X,{type:"option",children:m},d))}),(0,n.jsx)("div",{className:"px-2 py-1 overflow-y-auto grow",children:(0,n.jsx)("p",{className:(0,v.default)("text-secondary text-xs",o?"":"line-clamp-2"),children:e?.dashboard_description??" "})})]})}b();h();u();var i=c(E());var Be={heatmaps:"view the heatmap","add-action":"add actions","edit-action":"edit the action","add-experiment":"add web experiment","edit-experiment":"edit the experiment"},z=(0,i.kea)([(0,i.path)(["lib","components","iframedToolbarBrowser","iframedToolbarBrowserLogic"]),(0,i.props)({automaticallyAuthorizeBrowserUrl:!1}),(0,i.connect)({values:[w({...y,type:"TOOLBAR_URLS"}),["urlsKeyed","checkUrlIsAuthorized"],A,["currentTeam"]],actions:[w({...y,type:"TOOLBAR_URLS"}),["addUrl"],A,["updateCurrentTeamSuccess"]]}),(0,i.actions)({setBrowserUrl:e=>({url:e}),setProposedBrowserUrl:e=>({url:e}),onIframeLoad:!0,sendToolbarMessage:(e,a)=>({type:e,payload:a}),patchHeatmapFilters:e=>({filters:e}),setHeatmapColorPalette:e=>({Palette:e}),setHeatmapFixedPositionMode:e=>({mode:e}),setCommonFilters:e=>({filters:e}),setIframeWidth:e=>({width:e}),setIframeBanner:e=>({banner:e}),startTrackingLoading:!0,stopTrackingLoading:!0,enableElementSelector:!0,disableElementSelector:!0,setNewActionName:e=>({name:e}),toolbarMessageReceived:(e,a)=>({type:e,payload:a}),setCurrentPath:e=>({path:e}),setInitialPath:e=>({path:e})}),(0,i.reducers)(({props:e})=>({commonFilters:[{date_from:"-7d"},{setCommonFilters:(a,{filters:r})=>r}],heatmapColorPalette:["default",{setHeatmapColorPalette:(a,{Palette:r})=>r}],heatmapFilters:[k,{patchHeatmapFilters:(a,{filters:r})=>({...a,...r})}],heatmapFixedPositionMode:["fixed",{setHeatmapFixedPositionMode:(a,{mode:r})=>r}],iframeWidth:[null,{setIframeWidth:(a,{width:r})=>r}],browserUrl:[null,{persist:e.userIntent=="heatmaps"},{setBrowserUrl:(a,{url:r})=>r}],currentPath:["",{setCurrentPath:(a,{path:r})=>r}],initialPath:["",{setInitialPath:(a,{path:r})=>r}],loading:[!1,{setBrowserUrl:(a,{url:r})=>r?.trim().length?!0:a,setIframeBanner:(a,{banner:r})=>r?.level=="error"?!1:a,startTrackingLoading:()=>!0,stopTrackingLoading:()=>!1}],iframeBanner:[null,{setIframeBanner:(a,{banner:r})=>r}],proposedBrowserUrl:[null,{setProposedBrowserUrl:(a,{url:r})=>r}]})),(0,i.selectors)({isBrowserUrlAuthorized:[e=>[e.browserUrl,e.checkUrlIsAuthorized],(e,a)=>e?a(e):!1],isProposedBrowserUrlAuthorized:[e=>[e.proposedBrowserUrl,e.checkUrlIsAuthorized],(e,a)=>e?a(e):!1],viewportRange:[e=>[e.heatmapFilters,e.iframeWidth],(e,a)=>a?W(e,a):{min:0,max:1800}],currentFullUrl:[e=>[e.browserUrl,e.currentPath],(e,a)=>e?e+"/"+a:null]}),(0,i.listeners)(({actions:e,cache:a,props:r,values:t})=>({sendToolbarMessage:({type:o,payload:s})=>{r.iframeRef?.current?.contentWindow?.postMessage({type:o,payload:s},"*")},setProposedBrowserUrl:({url:o})=>{o&&(r.automaticallyAuthorizeBrowserUrl&&!t.isProposedBrowserUrlAuthorized?e.addUrl(o):e.setBrowserUrl(o))},patchHeatmapFilters:({filters:o})=>{e.sendToolbarMessage("ph-patch-heatmap-filters",{filters:o})},setHeatmapFixedPositionMode:({mode:o})=>{e.sendToolbarMessage("ph-heatmaps-fixed-position-mode",{fixedPositionMode:o})},setHeatmapColorPalette:({Palette:o})=>{e.sendToolbarMessage("ph-heatmaps-color-palette",{colorPalette:o})},setCommonFilters:({filters:o})=>{e.sendToolbarMessage("ph-heatmaps-common-filters",{commonFilters:o})},enableElementSelector:()=>{e.sendToolbarMessage("ph-element-selector",{enabled:!0})},disableElementSelector:()=>{e.sendToolbarMessage("ph-element-selector",{enabled:!1})},setNewActionName:({name:o})=>{e.sendToolbarMessage("ph-new-action-name",{name:o})},onIframeLoad:()=>{let o=()=>{switch(e.sendToolbarMessage("ph-app-init",{filters:t.heatmapFilters,colorPalette:t.heatmapColorPalette,fixedPositionMode:t.heatmapFixedPositionMode,commonFilters:t.commonFilters}),r.userIntent){case"heatmaps":e.sendToolbarMessage("ph-heatmaps-config",{enabled:!0});break}},s=m=>{let d=m?.data?.type,I=m?.data?.payload;if(e.toolbarMessageReceived(d,I),!(!d||!d.startsWith("ph-"))){if(!t.checkUrlIsAuthorized(m.origin)){console.warn("ignoring message from iframe with origin not in authorized toolbar urls",m.origin,m.data);return}switch(d){case"ph-toolbar-init":return o();case"ph-toolbar-ready":return r.userIntent==="heatmaps"?(g.capture("in-app heatmap frame loaded",{inapp_heatmap_page_url_visited:t.browserUrl,inapp_heatmap_filters:t.heatmapFilters,inapp_heatmap_color_palette:t.heatmapColorPalette,inapp_heatmap_fixed_position_mode:t.heatmapFixedPositionMode}),e.startTrackingLoading()):void 0;case"ph-toolbar-heatmap-loading":return e.startTrackingLoading();case"ph-toolbar-heatmap-loaded":return g.capture("in-app heatmap loaded",{inapp_heatmap_page_url_visited:t.browserUrl,inapp_heatmap_filters:t.heatmapFilters,inapp_heatmap_color_palette:t.heatmapColorPalette,inapp_heatmap_fixed_position_mode:t.heatmapFixedPositionMode}),e.stopTrackingLoading();case"ph-toolbar-heatmap-failed":g.capture("in-app heatmap failed",{inapp_heatmap_page_url_visited:t.browserUrl,inapp_heatmap_filters:t.heatmapFilters,inapp_heatmap_color_palette:t.heatmapColorPalette,inapp_heatmap_fixed_position_mode:t.heatmapFixedPositionMode}),e.stopTrackingLoading(),e.setIframeBanner({level:"error",message:"The heatmap failed to load."});return;case"ph-new-action-created":e.setNewActionName(null),e.disableElementSelector();return;case"ph-toolbar-navigated":return e.setCurrentPath(I.path.replace(/^\/+/,""));default:console.warn(`[PostHog Heatmaps] Received unknown child window message: ${d}`)}}};window.addEventListener("message",s,!1),o()},setBrowserUrl:({url:o})=>{o?.trim().length&&e.startTrackingLoading()},startTrackingLoading:()=>{e.setIframeBanner(null),clearTimeout(a.errorTimeout),a.errorTimeout=setTimeout(()=>{e.setIframeBanner({level:"error",message:"The heatmap failed to load (or is very slow)."})},7500),clearTimeout(a.warnTimeout),a.warnTimeout=setTimeout(()=>{e.setIframeBanner({level:"warning",message:"Still waiting for the toolbar to load."})},3e3)},stopTrackingLoading:()=>{e.setIframeBanner(null),clearTimeout(a.errorTimeout),clearTimeout(a.warnTimeout)},setIframeBanner:({banner:o})=>{g.capture("in-app iFrame banner set",{level:o?.level,message:o?.message})},updateCurrentTeamSuccess:()=>{r.automaticallyAuthorizeBrowserUrl&&t.proposedBrowserUrl&&t.currentTeam?.app_urls?.includes(t.proposedBrowserUrl)&&(e.setBrowserUrl(t.proposedBrowserUrl),e.setProposedBrowserUrl(null))}})),(0,i.afterMount)(({actions:e,values:a})=>{a.browserUrl?.trim().length&&e.startTrackingLoading()}),(0,i.beforeUnmount)(({actions:e,props:a})=>{a.clearBrowserUrlOnUnmount&&e.setBrowserUrl("")})]);b();h();u();var l=c(E());var Y={id:"$pageview",math:"dau",type:"events"},ze=(0,l.kea)([(0,l.path)(["scenes","dashboard","DashboardTemplateVariablesLogic"]),(0,l.props)({variables:[]}),(0,l.connect)({actions:[z,["toolbarMessageReceived","disableElementSelector"]]}),(0,l.actions)({setVariables:e=>({variables:e}),setVariable:(e,a)=>({variable_name:e,filterGroup:a}),setVariableFromAction:(e,a)=>({variableName:e,action:a}),setVariableForPageview:(e,a)=>({variableName:e,url:a}),setVariableForScreenview:e=>({variableName:e}),setActiveVariableIndex:e=>({index:e}),incrementActiveVariableIndex:!0,possiblyIncrementActiveVariableIndex:!0,resetVariable:e=>({variableId:e}),goToNextUntouchedActiveVariableIndex:!0,setIsCurrentlySelectingElement:e=>({isSelecting:e}),setActiveVariableCustomEventName:e=>({customEventName:e}),maybeResetActiveVariableCustomEventName:!0}),(0,l.reducers)({variables:[[],{setVariables:(e,{variables:a})=>a.map(r=>r.default&&!M(r.default)?r:{...r,default:Y}),setVariable:(e,{variable_name:a,filterGroup:r})=>{let t=Object.keys(r).filter(o=>(r[o]||[])?.length>0)?.[0];return t?e.map(o=>o.name===a&&r?.[t]?.length&&r?.[t]?.[0]?{...o,default:r[t]?.[0]||{},touched:!0}:{...o}):e},resetVariable:(e,{variableId:a})=>e.map(r=>r.id===a?{...r,default:Y,touched:!1}:{...r})}],activeVariableIndex:[0,{setActiveVariableIndex:(e,{index:a})=>a,incrementActiveVariableIndex:e=>e+1}],activeVariableCustomEventName:[null,{setActiveVariableCustomEventName:(e,{customEventName:a})=>a}],isCurrentlySelectingElement:[!1,{setIsCurrentlySelectingElement:(e,{isSelecting:a})=>a}]}),(0,l.selectors)(()=>({activeVariable:[e=>[e.variables,e.activeVariableIndex],(e,a)=>e[a]],allVariablesAreTouched:[e=>[e.variables],e=>e.every(a=>a.touched)],hasTouchedAnyVariable:[e=>[e.variables],e=>e.some(a=>a.touched)]})),(0,l.listeners)(({actions:e,props:a,values:r})=>({possiblyIncrementActiveVariableIndex:()=>{a.variables.length>0&&r.activeVariableIndex<a.variables.length-1&&e.incrementActiveVariableIndex()},goToNextUntouchedActiveVariableIndex:()=>{let t=r.variables.findIndex((o,s)=>!o.touched&&s>r.activeVariableIndex);if(t!==-1){e.setActiveVariableIndex(t);return}t==-1&&(t=r.variables.findIndex(o=>!o.touched),t==-1&&(t=r.activeVariableIndex)),e.setActiveVariableIndex(t)},setVariableFromAction:({variableName:t,action:o})=>{let s=t.replace(/\s-\s\d+/g,""),d={actions:[{id:o.id.toString(),math:"dau",name:o.name,custom_name:s,order:0,type:"actions",selector:o.steps?.[0]?.selector,href:o.steps?.[0]?.href,url:o.steps?.[0]?.url}]};e.setVariable(s,d),e.setIsCurrentlySelectingElement(!1)},setVariableForPageview:({variableName:t,url:o})=>{let m={events:[{id:"$pageview",math:"dau",type:"events",order:0,name:"$pageview",custom_name:t,properties:[{key:"$current_url",value:o,operator:"icontains",type:"event"}]}]};e.setVariable(t,m),e.setIsCurrentlySelectingElement(!1)},setVariableForScreenview:({variableName:t})=>{let s={events:[{id:"$screenview",math:"dau",type:"events",order:0,name:"$screenview",custom_name:t}]};e.setVariable(t,s),e.setIsCurrentlySelectingElement(!1)},toolbarMessageReceived:({type:t,payload:o})=>{t==="ph-new-action-created"&&(e.setVariableFromAction(o.action.name,o.action),e.disableElementSelector())},maybeResetActiveVariableCustomEventName:()=>{!r.activeVariable?.touched||!r.activeVariable?.default?.custom_event?e.setActiveVariableCustomEventName(null):r.activeVariable?.default?.custom_event&&e.setActiveVariableCustomEventName(r.activeVariable.default.id)}})),(0,l.propsChanged)(({actions:e,props:a},r)=>{a.variables!==r.variables&&e.setVariables(a.variables)})]);export{Ve as a,Be as b,z as c,ze as d};
//# sourceMappingURL=/static/chunk-MHUMFW53.js.map
