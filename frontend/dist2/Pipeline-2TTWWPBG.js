import{a as U,b as Wn,d as jn}from"/static/chunk-2KRNMCWE.js";import{b as De,c as Jn,d as Gn}from"/static/chunk-VUSJMGUX.js";import{b as Ye,c as be,d as $n}from"/static/chunk-4QFQ4UPP.js";import{a as zn}from"/static/chunk-5SPEHGYT.js";import{a as Hn}from"/static/chunk-A6KV2BLY.js";import"/static/chunk-G6Q3YRDS.js";import{a as Bn}from"/static/chunk-MEAB657I.js";import"/static/chunk-4HIBDE5Y.js";import"/static/chunk-LYMEBJGW.js";import"/static/chunk-QIBQKJHN.js";import{s as Un}from"/static/chunk-44P5EQSU.js";import{a as q}from"/static/chunk-GH3IWF3M.js";import"/static/chunk-HRNZBUVG.js";import{c as te,e as fe}from"/static/chunk-OKGJSIGC.js";import{a as Rn}from"/static/chunk-JZCOVRBI.js";import{$a as un,Ac as dn,Ae as ce,Bi as _n,Do as N,Eo as Oe,Hg as Cn,If as Sn,Io as W,Lb as cn,Nf as Tn,Oe as yn,Of as Ln,Pf as vn,Pg as we,Qd as ze,Rf as Nn,Sa as pe,Sd as y,Sm as _e,Ta as k,Tc as gn,Tm as En,Uf as kn,Um as Ee,Vc as fn,Vd as V,Vm as xn,Wd as ve,Wm as ne,Za as gt,_m as Xe,a as R,af as Ke,b as on,ce as Ne,de as ke,ee as $e,en as xe,f as an,fe as ue,gn as Ie,h as dt,hi as An,hn as In,ie as Ce,ii as wn,jn as me,kc as mn,ke as Ae,kn as de,le as Z,ln as On,m as ln,mn as Dn,nn as ge,qn as Fn,r as S,rn as ae,td as hn,tn as Mn,ve as ee,vo as G,x as pn,xd as bn,xo as he,yf as Pn,ze as B}from"/static/chunk-RFJTZKD6.js";import"/static/chunk-XPJ4MQJV.js";import{F as rn,Ha as sn,a as mt}from"/static/chunk-3UDJFOQH.js";import"/static/chunk-HHT4SG7V.js";import"/static/chunk-K7LQKAJG.js";import"/static/chunk-QQTK3LZH.js";import"/static/chunk-IJQNM355.js";import"/static/chunk-4CN6THWS.js";import"/static/chunk-272RTCFX.js";import"/static/chunk-2ROB4QWU.js";import"/static/chunk-ALT2ZZSO.js";import"/static/chunk-UE6SLBBN.js";import"/static/chunk-GINZUAUY.js";import"/static/chunk-SQELCOUW.js";import"/static/chunk-IGYUTZ65.js";import"/static/chunk-YM6UBNGD.js";import"/static/chunk-C6TQ5FFZ.js";import"/static/chunk-GXGA523B.js";import"/static/chunk-N4MMWRNK.js";import"/static/chunk-NRLAI7OY.js";import"/static/chunk-LVVHNICT.js";import"/static/chunk-2AXSSSSX.js";import"/static/chunk-DGXQI7RB.js";import"/static/chunk-HUCRWDLX.js";import"/static/chunk-RFEQG3YN.js";import"/static/chunk-PUISI233.js";import{d as p,e as f,g as h,j as b}from"/static/chunk-SJXEOBQC.js";f();b();h();var Le=p(R()),ut=p(an());f();b();h();var A=p(R());f();b();h();var ye=p(R()),Me=p(un());f();b();h();var x=p(R()),Xn=p(un());var Ve=(0,x.kea)([(0,x.props)({}),(0,x.key)(({pluginId:e})=>e),(0,x.path)(e=>["scenes","pipeline","appsCodeLogic",e]),(0,x.actions)({setCurrentFile:e=>({currentFile:e}),editAppCode:!0,cancelEditing:!0,fetchPluginSource:!0,fetchPluginSourceComplete:!0,setFilenames:e=>({code:e})}),(0,x.reducers)({currentFile:["plugin.json",{setCurrentFile:(e,{currentFile:n})=>n}],editingAppCode:[!1,{editAppCode:()=>!0,cancelEditing:()=>!1,submitPluginSourceSuccess:()=>!1}],pluginSourceLoading:[!1,{fetchPluginSource:()=>!0,fetchPluginSourceComplete:()=>!1}],filenames:[[],{setFilenames:(e,{code:n})=>n?Object.keys(n):[]}]}),(0,x.listeners)(({actions:e,props:n})=>({cancelEditing:async()=>{e.fetchPluginSource()},fetchPluginSource:async()=>{try{let o=await W.get(`api/organizations/@current/plugins/${n.pluginId}/source`),r={};for(let[i,s]of Object.entries(o||{}))if(s&&i.match(/\.(ts|tsx|js|jsx|json)$/))try{let d=await Kn(i,s);r[i]=d}catch{r[i]=s}e.setPluginSourceValues(r),e.setFilenames(r)}finally{e.fetchPluginSourceComplete()}}})),(0,Xn.forms)(({actions:e,props:n,values:o})=>({pluginSource:{defaults:{},preSubmit:async()=>{let r={},i={};for(let[s,d]of Object.entries(o.pluginSource))if(d&&s.match(/\.(ts|tsx|js|jsx|json)$/))try{let u=await Kn(s,d);u!==d&&(r[s]=u)}catch(u){i[s]=u.message}Object.keys(r).length>0&&e.setPluginSourceValues(r),e.setPluginSourceManualErrors(i)},submit:async()=>{let r=await W.update(`api/organizations/@current/plugins/${n.pluginId}/update_source`,o.pluginSource);e.setPluginSourceValues(r)}}})),(0,x.afterMount)(({actions:e})=>{e.fetchPluginSource()})]);async function Kn(e,n){if(e.endsWith(".json"))return JSON.stringify(JSON.parse(n),null,4)+`
`;let o=(await import("/static/standalone-4LNSLDH6.js")).default,r=(await import("/static/parser-typescript-3OQOFSNN.js")).default;return o.format(n,{filepath:e,parser:"typescript",plugins:[r],semi:!1,trailingComma:"es5",singleQuote:!0,tabWidth:4,printWidth:120})}f();b();h();var I=p(R()),qn=p(gt());f();b();h();var Fe=(s=>(s.FilterEvent="filterEvent",s.ModifyEvent="modifyEvent",s.ComposeWebhook="composeWebhook",s.Site="site",s.Frontend="frontend",s))(Fe||{});function Yn(e,n){switch(n){case"filterEvent":return{"plugin.json":JSON.stringify({name:e,config:[{markdown:"Specify your config here"},{key:"eventToSkip",name:"Event to skip",type:"string",hint:"If the event name matches this, it will be skipped",default:"$pageview",required:!1}]},null,4),"index.ts":`// Learn more about plugins at: https://posthog.com/docs/apps/build

// Processes each event, optionally dropping it
export function processEvent(event, { config }) {
    if (event.event === config.eventToSkip) {
        return null
    }
    return event
}

// Runs when the plugin is loaded, allows for preparing it as needed
export function setupPlugin (meta) {
    console.log(\`The date is \${new Date().toDateString()}\`)
}`};case"modifyEvent":return{"plugin.json":JSON.stringify({name:e,config:[{markdown:"Specify your config here"},{key:"propertyToRemove",name:"Property to remove",type:"string",hint:"This property will be removed from all events",default:"$browser",required:!1}]},null,4),"index.ts":`// Learn more about plugins at: https://posthog.com/docs/apps/build

// Processes each event, optionally modify it
export function processEvent(event, { config }) {
    event.properties[config.propertyToRemove] = undefined
    return event
}

// Runs when the plugin is loaded, allows for preparing it as needed
export function setupPlugin (meta) {
    console.log(\`The date is \${new Date().toDateString()}\`)
}`};case"composeWebhook":return{"plugin.json":JSON.stringify({name:e,config:[{markdown:"Specify your config here"},{key:"url",name:"The destination url",type:"string",hint:"Where the webhook will be sent to",default:"",required:!0}]},null,4),"index.ts":`// Learn more about plugins at: https://posthog.com/docs/apps/build
import { PostHogEvent, Webhook } from '@posthog/plugin-scaffold'

export function composeWebhook(event: PostHogEvent, { config }: any): Webhook {
    return {
        url: config.url,
        body: JSON.stringify(event),
        headers: {
            'Content-Type': 'application/json',
        },
        method: 'POST',
    }
}`};case"site":return{"plugin.json":JSON.stringify({name:e,config:[{markdown:"Specify your config here"},{key:"name",name:"Person to greet",type:"string",hint:"Used to personalise the property `hello`",default:"world",required:!1}]},null,4),"site.ts":`export function inject({ config, posthog }) {
    console.log('Hello from PostHog-JS')
}
"`};case"frontend":return{"plugin.json":JSON.stringify({name:e,config:[{markdown:"Specify your config here"},{key:"name",name:"Person to greet",type:"string",hint:"Used to personalise the property `hello`",default:"world",required:!1}]},null,4),"frontend.tsx":`import React from "react"

                export const scene = {
                    title: "My Stuff",
                    component: function MyStuff({ config }) {
                        return (
                            <div>
                                <h1>My Favourite Links</h1>
                                <ul>
                                    <li>
                                        <a href="https://news.ycombinator.com">The NEWS</a>
                                    </li>
                                </ul>
                                <h1>My Favourite Cow</h1>
                                <img src="https://media.giphy.com/media/RYKFEEjtYpxL2/giphy.gif" />
                            </div>
                        )
                    },
                }`}}}function qe(e,n,o){on.capture(e,{plugin_name:n.name,plugin_url:n.url?.startsWith("file:")?"file://masked-local-path":n.url,plugin_tag:n.tag,plugin_installation_type:o})}var C=(0,I.kea)([(0,I.path)(["scenes","pipeline","appsManagementLogic"]),(0,I.connect)({values:[Oe,["user"],ne,["canGloballyManagePlugins"]]}),(0,I.actions)({setPluginUrl:e=>({pluginUrl:e}),setLocalPluginPath:e=>({localPluginPath:e}),setSourcePluginName:e=>({sourcePluginName:e}),setSourcePluginKind:e=>({sourcePluginKind:e}),uninstallPlugin:e=>({id:e}),installPlugin:(e,n)=>({pluginType:e,url:n}),installPluginFromUrl:e=>({url:e}),installSourcePlugin:e=>({name:e}),installLocalPlugin:e=>({path:e}),patchPlugin:(e,n={})=>({id:e,pluginChanges:n}),updatePlugin:e=>({id:e}),checkForUpdates:!0,checkedForUpdates:!0,setPluginLatestTag:(e,n)=>({id:e,latestTag:n})}),(0,qn.loaders)(({values:e})=>({plugins:[{},{loadPlugins:async()=>Dn("api/organizations/@current/plugins"),installPlugin:async({pluginType:n,url:o})=>{if(!e.canInstallPlugins)return V.error("You don't have permission to install apps."),e.plugins;let r={plugin_type:n};if(o||n==="repository")r.url=o;else if(n==="custom")r.url=e.pluginUrl;else if(n==="local")r.url=`file:${e.localPluginPath}`;else if(n==="source")r.name=e.sourcePluginName;else return V.error("Unsupported installation type."),e.plugins;let i=await W.create("api/organizations/@current/plugins",r);return n==="source"&&await W.update(`api/organizations/@current/plugins/${i.id}/update_source`,Yn(e.sourcePluginName,e.sourcePluginKind)),qe("plugin installed",i,n),{...e.plugins,[i.id]:i}},uninstallPlugin:async({id:n})=>{e.canGloballyManagePlugins||V.error("You don't have permission to manage apps."),await W.delete(`api/organizations/@current/plugins/${n}`),qe("plugin uninstalled",e.plugins[n],e.plugins[n].plugin_type);let{[n]:o,...r}=e.plugins;return r},patchPlugin:async({id:n,pluginChanges:o})=>{e.canGloballyManagePlugins||V.error("You don't have permission to update apps.");let r=await W.update(`api/organizations/@current/plugins/${n}`,o);return{...e.plugins,[n]:r}},setPluginLatestTag:async({id:n,latestTag:o})=>({...e.plugins,[n]:{...e.plugins[n],latest_tag:o}}),updatePlugin:async({id:n})=>{e.canGloballyManagePlugins||V.error("You don't have permission to update apps.");let o=await W.create(`api/organizations/@current/plugins/${n}/upgrade`);return qe("plugin updated",e.plugins[n],e.plugins[n].plugin_type),V.success(`Plugin ${o.name} updated!`),{...e.plugins,[n]:o}}}],unusedPlugins:[[],{loadUnusedPlugins:async()=>await W.get("api/organizations/@current/plugins/unused")}]})),(0,I.reducers)({installingPluginUrl:[null,{installPlugin:(e,{url:n})=>n||null,installPluginSuccess:()=>null,installPluginFailure:()=>null}],pluginUrl:["",{setPluginUrl:(e,{pluginUrl:n})=>n,installPluginSuccess:()=>""}],localPluginPath:["",{setLocalPluginPath:(e,{localPluginPath:n})=>n,installPluginSuccess:()=>""}],sourcePluginName:["",{setSourcePluginName:(e,{sourcePluginName:n})=>n,installPluginSuccess:()=>""}],sourcePluginKind:["filterEvent",{setSourcePluginKind:(e,{sourcePluginKind:n})=>n,installPluginSuccess:()=>"filterEvent"}],checkingForUpdates:[!1,{checkForUpdates:()=>!0,checkedForUpdates:()=>!1}]}),(0,I.selectors)({canInstallPlugins:[e=>[e.user],e=>xn(e?.organization)],inlinePlugins:[e=>[e.plugins],e=>Object.values(e).filter(n=>n.plugin_type==="inline")],appPlugins:[e=>[e.plugins],e=>Object.values(e).filter(n=>n.plugin_type!=="inline")],globalPlugins:[e=>[e.appPlugins],e=>Object.values(e).filter(n=>n.is_global)],localPlugins:[e=>[e.appPlugins],e=>Object.values(e).filter(n=>!n.is_global)],missingGlobalPlugins:[e=>[e.appPlugins],e=>{let n=new Set(Object.values(e).map(o=>o.url));return Array.from(xe).filter(o=>!n.has(o))}],shouldBeGlobalPlugins:[e=>[e.appPlugins],e=>Object.values(e).filter(n=>n.url&&xe.has(n.url)&&!n.is_global)],shouldNotBeGlobalPlugins:[e=>[e.appPlugins],e=>Object.values(e).filter(n=>!(n.url&&xe.has(n.url))&&n.is_global)],updatablePlugins:[e=>[e.appPlugins],e=>Object.values(e).filter(n=>n.plugin_type!=="source"&&!n.url?.startsWith("file:"))],pluginsNeedingUpdates:[e=>[e.updatablePlugins],e=>e.filter(n=>n.latest_tag&&n.tag!==n.latest_tag)]}),(0,I.listeners)(({actions:e,values:n})=>({checkForUpdates:async()=>{await Promise.all(n.updatablePlugins.map(async o=>{try{let r=await W.get(`api/organizations/@current/plugins/${o.id}/check_for_updates`);e.setPluginLatestTag(o.id,r.plugin.latest_tag)}catch(r){V.error(`Error checking for updates for ${o.name}: ${JSON.stringify(r)}`)}})),e.checkedForUpdates()}})),(0,I.afterMount)(({actions:e})=>{e.loadPlugins(),e.loadUnusedPlugins(),e.checkForUpdates()})]);var g=p(S());function Qn({pluginId:e,pluginType:n}){let o={pluginId:e},r=Ve(o),{currentFile:i,filenames:s,pluginSource:d,pluginSourceLoading:u,editingAppCode:E,pluginSourceAllErrors:c,pluginSourceHasErrors:K,isPluginSourceSubmitting:j}=(0,ye.useValues)(r),{setCurrentFile:ie,cancelEditing:se,editAppCode:v,submitPluginSource:T}=(0,ye.useActions)(r),{canGloballyManagePlugins:M,plugins:z}=(0,ye.useValues)(C);if(u)return(0,g.jsx)(ze,{});let L=M&&n==="source";return(0,g.jsxs)(g.Fragment,{children:[(0,g.jsx)(Ne,{onClose:se,isOpen:E,width:600,title:"Editing source code of "+z[e].name,description:(0,g.jsxs)("p",{children:["Read our"," ",(0,g.jsx)(k,{to:"https://posthog.com/docs/apps/build",target:"_blank",children:"app building overview in PostHog docs"})," ","for a good grasp of the possibilities."]}),footer:(0,g.jsxs)(g.Fragment,{children:[(0,g.jsx)(y,{type:"secondary",onClick:se,children:"Cancel"}),(0,g.jsx)(y,{loading:j,type:"primary",onClick:()=>T(),children:"Save"})]}),children:(0,g.jsx)(Me.Form,{logic:Ve,props:o,formKey:"pluginSource",children:L?(0,g.jsx)(g.Fragment,{children:u?(0,g.jsx)(ze,{}):(0,g.jsx)(g.Fragment,{children:(0,g.jsx)(ce,{activeKey:i,onChange:P=>ie(P),tabs:Object.values(s).map(P=>({label:P,key:P,content:(0,g.jsxs)(g.Fragment,{children:[K&&(0,g.jsx)(ve,{type:"error",children:Object.entries(c).map(([l,X])=>(0,g.jsxs)("p",{children:[l,": ",X]},l))}),(0,g.jsx)(Me.Field,{name:[i],children:({value:l,onChange:X})=>(0,g.jsx)(Cn,{path:i,language:i.endsWith(".json")?"json":"typescript",value:l,onChange:le=>X(le??""),height:700,options:{minimap:{enabled:!1}}})})]})}))})})}):null})}),(0,g.jsx)(ce,{activeKey:i,onChange:P=>ie(P),tabs:Object.values(s).map(P=>({label:P,key:P,content:(0,g.jsx)("div",{className:"mr-4",children:(0,g.jsx)(yn,{language:i.endsWith(".json")?"json":"javascript",thing:i,maxLinesWithoutExpansion:20,actions:L?(0,g.jsx)(y,{onClick:v,icon:(0,g.jsx)(dn,{}),title:"Edit the code",noPadding:!0}):void 0,wrap:!0,children:d[i]??""})})}))})]})}var t=p(S());function Zn(){C.mount();let{canInstallPlugins:e,canGloballyManagePlugins:n,missingGlobalPlugins:o,shouldBeGlobalPlugins:r,shouldNotBeGlobalPlugins:i,globalPlugins:s,localPlugins:d,inlinePlugins:u,pluginsLoading:E}=(0,A.useValues)(C),{isDev:c,isCloudOrDev:K}=(0,A.useValues)(Ke);return!e||!n?(0,t.jsx)(t.Fragment,{children:"You don't have permission to manage apps."}):(0,t.jsxs)("div",{className:"pipeline-apps-management-scene",children:[K&&!E&&(o.length>0||r.length>0||i.length>0)&&(0,t.jsx)(bt,{}),(0,t.jsx)("h2",{children:"Manual installation"}),(0,t.jsx)(Pt,{}),c&&(0,t.jsx)(St,{}),(0,t.jsx)(Tt,{}),(0,t.jsx)($e,{className:"my-6"}),(0,t.jsx)("h2",{children:"Installed apps"}),(0,t.jsx)(ft,{}),s&&(0,t.jsxs)(t.Fragment,{children:[(0,t.jsx)("h3",{className:"mt-3",children:"Global apps"}),(0,t.jsx)("p",{children:"These apps can be used in all organizations."}),(0,t.jsx)(Pe,{plugins:s})]}),d&&(0,t.jsxs)(t.Fragment,{children:[(0,t.jsx)("h3",{className:"mt-3",children:"Local apps"}),(0,t.jsx)("p",{children:"These apps can only be used by this organization, or ones with an existing plugin config."}),(0,t.jsx)(Pe,{plugins:d})]}),u&&(0,t.jsxs)(t.Fragment,{children:[(0,t.jsx)("h3",{className:"mt-3",children:"Inline plugins"}),(0,t.jsx)("p",{children:"These plugins are inlined into plugin-server code, any updates should be done there."}),(0,t.jsx)(ht,{plugins:u})]})]})}function ft(){let{updatablePlugins:e,pluginsNeedingUpdates:n,checkingForUpdates:o}=(0,A.useValues)(C),{checkForUpdates:r}=(0,A.useActions)(C);return(0,t.jsxs)(t.Fragment,{children:[e&&(0,t.jsx)(y,{type:"secondary",icon:(0,t.jsx)(fn,{}),onClick:r,loading:o,children:o?`Checking ${Object.keys(e).length} apps for updates`:"Check again for updates"}),n.length>0&&(0,t.jsxs)(t.Fragment,{children:[(0,t.jsx)("h3",{className:"mt-3",children:"Apps to update"}),(0,t.jsx)("p",{children:"These apps have newer commits in the repository they link to."}),(0,t.jsx)(Pe,{plugins:n})]})]})}function Pe({plugins:e}){let{unusedPlugins:n}=(0,A.useValues)(C),{uninstallPlugin:o,patchPlugin:r,updatePlugin:i}=(0,A.useActions)(C),s=u=>{ke.open({title:"Are you sure you wish to uninstall this app completely?",primaryButton:{children:"Uninstall",type:"secondary",status:"danger",onClick:()=>o(u)},secondaryButton:{children:"Cancel"}})},d=e.map(u=>({...u,key:u.id}));return(0,t.jsx)(t.Fragment,{children:(0,t.jsx)(B,{dataSource:d,columns:[{width:60,render:function(E,c){return(0,t.jsx)(Ie,{plugin:c})}},{title:"Name",render:function(E,c){return(0,t.jsxs)(t.Fragment,{children:[(0,t.jsxs)("div",{className:"flex gap-2 items-center",children:[(0,t.jsx)("span",{className:"font-semibold truncate",children:c.name}),c.latest_tag&&c.tag&&c.latest_tag!==c.tag&&(0,t.jsx)(k,{to:c.url+"/compare/"+c.tag+"..."+c.latest_tag,children:(0,t.jsx)(ue,{type:"completion",children:"See update diff"})})]}),(0,t.jsx)("div",{className:"text-sm",children:c.description})]})}},{title:"Capabilities",width:"30%",render:function(E,c){return(0,t.jsxs)(t.Fragment,{children:[(0,t.jsxs)("div",{className:"text-sm",children:["Methods: ",JSON.stringify(c.capabilities?.methods)]}),(0,t.jsxs)("div",{className:"text-sm",children:["Jobs: ",JSON.stringify(c.capabilities?.jobs)]}),(0,t.jsxs)("div",{className:"text-sm",children:["Scheduled tasks: ",JSON.stringify(c.capabilities?.scheduled_tasks)]})]})}},{title:"Actions",width:240,align:"right",render:function(E,c){return(0,t.jsxs)("div",{className:"flex items-center gap-2 justify-end",children:[c.latest_tag&&c.tag!=c.latest_tag&&(0,t.jsx)(y,{type:"secondary",size:"small",icon:(0,t.jsx)(cn,{}),onClick:()=>i(c.id),children:"Update"}),c.is_global?(0,t.jsx)(pe,{title:(0,t.jsxs)(t.Fragment,{children:["This app can currently be used by other organizations in this instance of PostHog. This action will ",(0,t.jsx)("b",{children:"disable and hide it"})," for all organizations that do not have an existing pluginconfig."]}),children:(0,t.jsx)(y,{type:"secondary",size:"small",icon:(0,t.jsx)(mn,{}),onClick:()=>r(c.id,{is_global:!1}),children:"Make local"})}):(0,t.jsx)(pe,{title:(0,t.jsxs)(t.Fragment,{children:["This action will mark this app as installed for"," ",(0,t.jsx)("b",{children:"all organizations"})," in this instance of PostHog."]}),children:(0,t.jsx)(y,{type:"secondary",size:"small",icon:(0,t.jsx)(bn,{}),onClick:()=>r(c.id,{is_global:!0}),children:"Make global"})}),(0,t.jsx)(y,{type:"secondary",status:"danger",size:"small",icon:(0,t.jsx)(hn,{}),disabledReason:n.includes(c.id)?void 0:"This app is still in use.","data-attr":"plugin-uninstall",onClick:()=>s(c.id),children:"Uninstall"})]})}}],expandable:{expandedRowRender:function(E){return(0,t.jsx)(Qn,{pluginId:E.id,pluginType:E.plugin_type})}}})})}function ht({plugins:e}){let n=e.map(o=>({...o,key:o.id}));return(0,t.jsx)(t.Fragment,{children:(0,t.jsx)(B,{dataSource:n,columns:[{title:"Name",render:function(r,i){return(0,t.jsxs)(t.Fragment,{children:[(0,t.jsx)("div",{className:"flex gap-2 items-center",children:(0,t.jsx)("span",{className:"font-semibold truncate",children:i.name})}),(0,t.jsx)("div",{className:"text-sm",children:i.description})]})}},{title:"Capabilities",width:"30%",render:function(r,i){return(0,t.jsxs)(t.Fragment,{children:[(0,t.jsxs)("div",{className:"text-sm",children:["Methods: ",JSON.stringify(i.capabilities?.methods)]}),(0,t.jsxs)("div",{className:"text-sm",children:["Jobs: ",JSON.stringify(i.capabilities?.jobs)]}),(0,t.jsxs)("div",{className:"text-sm",children:["Scheduled tasks: ",JSON.stringify(i.capabilities?.scheduled_tasks)]})]})}},{title:"Global",render:function(r,i){return(0,t.jsx)("span",{children:i.is_global?"Yes":"No"})}}]})})}function bt(){let{shouldNotBeGlobalPlugins:e,shouldBeGlobalPlugins:n}=(0,A.useValues)(C);return(0,t.jsxs)(t.Fragment,{children:[(0,t.jsx)("h2",{children:"Out-of-sync global apps"}),(0,t.jsx)(ve,{type:"warning",children:"This PostHog Cloud instance is currently out of sync with the GLOBAL_PLUGINS list."}),(0,t.jsx)(yt,{}),e&&(0,t.jsxs)(t.Fragment,{children:[(0,t.jsx)("h3",{className:"mt-3",children:"Apps that should NOT be global"}),(0,t.jsx)("p",{children:"These apps should NOT be global according to repo."}),(0,t.jsx)(Pe,{plugins:e})]}),n&&(0,t.jsxs)(t.Fragment,{children:[(0,t.jsx)("h3",{className:"mt-3",children:"Apps that SHOULD be global"}),(0,t.jsx)("p",{children:"These already installed apps should be global according to repo."}),(0,t.jsx)(Pe,{plugins:n})]}),(0,t.jsx)($e,{className:"my-6"})]})}function yt(){let{missingGlobalPlugins:e,pluginsLoading:n,installingPluginUrl:o}=(0,A.useValues)(C),{installPlugin:r}=(0,A.useActions)(C);if(e.length===0)return(0,t.jsx)(t.Fragment,{});let i=e.map(s=>({url:s}));return(0,t.jsxs)(t.Fragment,{children:[(0,t.jsx)("h3",{className:"mt-3",children:"Missing global apps"}),(0,t.jsx)("p",{children:"These plugins are defined in the GLOBAL_PLUGINS list, but are not installed on this instance."}),(0,t.jsx)(B,{dataSource:i,columns:[{title:"URL",key:"url",render:function(d,{url:u}){return(0,t.jsx)(k,{to:u,target:"_blank",children:u})}},{title:"Actions",width:0,align:"right",render:function(d,{url:u}){return(0,t.jsx)(y,{type:"secondary",size:"small",loading:n&&o===u,onClick:()=>r("repository",u),id:`install-plugin-${u}`,children:"Install"})}}]})]})}function Pt(){let{isCloudOrDev:e}=(0,A.useValues)(Ke),{pluginUrl:n}=(0,A.useValues)(C),{setPluginUrl:o,installPlugin:r}=(0,A.useActions)(C),i="https://github.com/PostHog/",s=n?void 0:"Please enter a url";return e&&(s=n.startsWith(i)?void 0:"Please enter a PostHog org repo url"),(0,t.jsxs)(t.Fragment,{children:[(0,t.jsx)("h3",{className:"mt-3",children:"Install from GitHub"}),(0,t.jsx)("p",{children:e?(0,t.jsxs)(t.Fragment,{children:["Only PostHog organization repositories are allowed, i.e. starting with"," ",(0,t.jsx)(k,{to:i,target:"blank",children:i})," "]}):(0,t.jsxs)(t.Fragment,{children:["For private repositories, append ",(0,t.jsx)("code",{children:"?private_token=TOKEN"})," to the end of the URL."]})}),(0,t.jsxs)("div",{className:"flex items-center gap-2",children:[(0,t.jsx)(Ce,{value:n,onChange:o,placeholder:"https://github.com/PostHog/posthog-hello-world-plugin",className:"flex-1"}),(0,t.jsx)(y,{disabledReason:s,type:"primary",onClick:()=>r("custom"),children:"Fetch and install"})]})]})}function St(){let{localPluginPath:e}=(0,A.useValues)(C),{setLocalPluginPath:n,installPlugin:o}=(0,A.useActions)(C);return(0,t.jsx)(t.Fragment,{children:(0,t.jsxs)("div",{children:[(0,t.jsx)("h3",{className:"mt-3",children:"Install from local path"}),(0,t.jsx)("p",{children:"To install a local app from this computer/server, give its full path below."}),(0,t.jsxs)("div",{className:"flex items-center gap-2",children:[(0,t.jsx)(Ce,{value:e,onChange:n,placeholder:"/var/posthog/apps/helloworldapp",className:"flex-1"}),(0,t.jsx)(y,{disabledReason:e?void 0:"Please enter a path",type:"primary",onClick:()=>o("local"),children:"Install"})]})]})})}function Tt(){let{sourcePluginName:e,sourcePluginKind:n}=(0,A.useValues)(C),{setSourcePluginName:o,installPlugin:r,setSourcePluginKind:i}=(0,A.useActions)(C),s=Object.values(Fe).map(d=>({label:d,onClick:()=>{i(d)}}));return(0,t.jsxs)("div",{children:[(0,t.jsx)("h3",{className:"mt-3",children:"Install by writing source code"}),(0,t.jsxs)("p",{children:["To install a source app provide the name and start coding.",(0,t.jsxs)(k,{to:"https://posthog.com/docs/apps",target:"_blank",children:[" ","Read the documentation for more information!"]})]}),(0,t.jsxs)("div",{className:"flex items-center gap-2",children:[(0,t.jsx)(Ce,{value:e,onChange:o,placeholder:"Hello World App",className:"flex-1"}),(0,t.jsx)(Ae,{items:s,placement:"bottom-end",children:(0,t.jsx)(y,{size:"small",children:n})}),(0,t.jsx)(y,{disabledReason:e?void 0:"Please enter a name",type:"primary",onClick:()=>r("source"),children:"Install"})]})]})}f();b();h();var ot=p(dt()),Y=p(R());var Ue=p(mt());f();b();h();var et=p(R());var nt=p(S());function Qe({pipelineNode:e}){let n=$n({id:e.id}),{appMetricsResponse:o}=(0,et.useValues)(n),r=o?o.metrics.successes.slice(-7):[],i=o?o.metrics.failures.slice(-7):[],s=o?o.metrics.dates.slice(-7):[],d=[{color:"success",name:"Success",values:r}];return o?.metrics.failures.some(u=>u>0)&&d.push({color:"danger",name:"Failure",values:i}),(0,nt.jsx)(Rn,{loading:o===null,labels:s,data:d,className:"max-w-24 h-8",maximumIndicator:!1})}f();b();h();var Re=p(R());var w=p(S());function Be({asLegacyList:e}){let{loading:n,frontendApps:o}=(0,Re.useValues)(Ye),{toggleEnabled:r,loadPluginConfigs:i}=(0,Re.useActions)(Ye),s=o.length===0&&!n&&!e;return(0,w.jsxs)(w.Fragment,{children:[!e&&(0,w.jsx)(G,{caption:"Extend your web app with custom functionality.",buttons:(0,w.jsx)(U,{stage:"site-app"})}),!e&&(0,w.jsx)(q,{productName:"Site apps",thingName:"site app",productKey:"site_apps",description:"Site apps allow you to add custom functionality to your website using PostHog.",docsURL:"https://posthog.com/docs/apps/pineapple-mode",actionElementOverride:(0,w.jsx)(U,{stage:"site-app"}),isEmpty:s}),!s&&(0,w.jsxs)(w.Fragment,{children:[!n&&e&&(0,w.jsxs)(w.Fragment,{children:[(0,w.jsx)("h2",{className:"mt-4",children:"Legacy Site apps"}),(0,w.jsx)("p",{children:"These site apps are using an older system and should eventually be migrated over."})]}),(0,w.jsx)(B,{dataSource:o,size:"small",loading:n,columns:[de(),me(),te(),fe(),{width:0,render:function(u,E){return(0,w.jsx)(ee,{overlay:(0,w.jsx)(Z,{items:[...ge(E,r,i)]})})}}]})]})]})}var a=p(S());function Te({types:e}){let{destinations:n,loading:o}=(0,Y.useValues)(ae({types:e}));return(0,a.jsxs)(a.Fragment,{children:[e.includes("destination")?(0,a.jsxs)(a.Fragment,{children:[(0,a.jsx)(G,{caption:"Send your data in real time or in batches to destinations outside of PostHog.",buttons:(0,a.jsx)(U,{stage:"destination"})}),(0,a.jsx)(_n,{feature:"data_pipelines",className:"mb-2",children:(0,a.jsx)(q,{productName:"Pipeline destinations",thingName:"destination",productKey:"pipeline_destinations",description:"Pipeline destinations allow you to export data outside of PostHog, such as webhooks to Slack.",docsURL:"https://posthog.com/docs/cdp",actionElementOverride:(0,a.jsx)(U,{stage:"destination"}),isEmpty:n.length===0&&!o})})]}):e.includes("site_app")?(0,a.jsx)(G,{caption:"Run custom scripts on your website.",buttons:(0,a.jsx)(U,{stage:"site-app"})}):e.includes("transformation")?(0,a.jsx)(a.Fragment,{children:(0,a.jsx)(Lt,{types:e})}):null,(0,a.jsx)(He,{types:e}),(0,a.jsx)("div",{className:"mt-4"}),(0,a.jsx)("h2",{children:e.includes("destination")?"New destinations":e.includes("site_app")?"New site app":e.includes("transformation")?"New transformation":"New"}),(0,a.jsx)(jn,{types:e}),e.includes("site_app")?(0,a.jsx)(Be,{asLegacyList:!0}):null]})}function He({hideFeedback:e,hideAddDestinationButton:n,types:o}){let{canConfigurePlugins:r,canEnableDestination:i}=(0,Y.useValues)(ne),{loading:s,filteredDestinations:d,destinations:u,hiddenDestinations:E}=(0,Y.useValues)(ae({types:o})),{toggleNode:c,deleteNode:K,openReorderTransformationsModal:j}=(0,Y.useActions)(ae({types:o})),{resetFilters:ie}=(0,Y.useActions)(Fn({types:o})),se=o.includes("destination")||o.includes("transformation"),v=o.includes("destination"),T=o.includes("destination")||o.includes("site_destination")?"destination":o.includes("site_app")?"site app":"Hog function",M=u.filter(L=>L.stage==="transformation"&&L.enabled),z=o.includes("transformation");return(0,a.jsxs)("div",{className:"space-y-4",children:[(0,a.jsx)(Wn,{types:o,hideFeedback:e,hideAddDestinationButton:n}),o.includes("transformation")&&M.length>1&&(0,a.jsxs)("div",{className:"flex items-center gap-2",children:["Processed sequentially.",(0,a.jsx)(y,{onClick:()=>j(),noPadding:!0,id:"transformation-reorder",disabledReason:r?void 0:"You do not have permission to reorder Transformations.",children:"Change order"})]}),(0,a.jsx)(B,{dataSource:d,size:"small",loading:s,columns:[...z?[{title:"Prio",key:"order",width:0,align:"center",sorter:(L,P)=>{if(L.backend==="hog_function"&&P.backend==="hog_function"){let l=L.hog_function.execution_order||0,X=P.hog_function.execution_order||0;return l-X}return 0},render:function(P,l){if(l.backend==="hog_function"&&l.enabled){let le=d.filter(re=>re.backend==="hog_function"&&re.enabled).sort((re,ct)=>(re.hog_function.execution_order||0)-(ct.hog_function.execution_order||0)).findIndex(re=>re.id===l.id);return(0,a.jsx)("div",{className:"text-center",children:le+1})}return null}}]:[],{title:"App",width:0,render:function(P,l){switch(l.backend){case"plugin":return(0,a.jsx)(Ie,{plugin:l.plugin});case"hog_function":return(0,a.jsx)(Mn,{src:l.hog_function.icon_url,size:"small"});case"batch_export":return(0,a.jsx)(In,{type:l.service.type});default:return null}}},{title:"Name",sticky:!0,key:"name",dataIndex:"name",sorter:(L,P)=>(L.name||"").localeCompare(P.name||""),render:function(P,l){return(0,a.jsx)(we,{to:N.pipelineNode(Xe(l.stage),l.id,"configuration"),title:(0,a.jsx)(a.Fragment,{children:(0,a.jsx)(pe,{title:"Click to update configuration, view metrics, and more",children:(0,a.jsx)("span",{children:l.name})})}),description:l.description})}},...v?[{title:"Frequency",key:"interval",render:function(P,l){return"interval"in l?l.interval:null}}]:[],...se?[{title:"Last 7 days",render:function(P,l){return(0,a.jsx)(k,{to:N.pipelineNode(Xe(l.stage),l.id,"metrics"),children:l.backend==="hog_function"?(0,a.jsx)(Bn,{id:l.hog_function.id}):(0,a.jsx)(Qe,{pipelineNode:l})})}}]:[],te(),{title:"Status",key:"enabled",sorter:L=>L.enabled?1:-1,width:0,render:function(P,l){return l.backend==="hog_function"?(0,a.jsx)(Hn,{hogFunction:l.hog_function}):(0,a.jsx)(a.Fragment,{children:l.enabled?(0,a.jsx)(ue,{type:"success",children:"Active"}):(0,a.jsx)(ue,{type:"default",children:"Disabled"})})}},{width:0,render:function(P,l){return(0,a.jsx)(ee,{overlay:(0,a.jsx)(Z,{items:[{label:l.enabled?`Pause ${T}`:`Unpause ${T}`,onClick:()=>c(l,!l.enabled),disabledReason:r?!i(l)&&!l.enabled?`Data pipelines add-on is required for enabling new ${T}s`:void 0:`You do not have permission to toggle ${T}s.`},...On(l),{label:`Delete ${T}`,status:"danger",onClick:()=>K(l),disabledReason:r?void 0:`You do not have permission to delete ${T}.`}]})})}}],emptyState:u.length===0&&!s?"No destinations found":(0,a.jsxs)(a.Fragment,{children:["No destinations matching filters. ",(0,a.jsx)(k,{onClick:()=>ie(),children:"Clear filters"})," "]})}),E.length>0&&(0,a.jsxs)("div",{className:"text-secondary",children:[E.length," hidden. ",(0,a.jsx)(k,{onClick:()=>ie(),children:"Show all"})]})]})}function Lt({types:e}){let{reorderTransformationsModalOpen:n,destinations:o,temporaryTransformationOrder:r,loading:i}=(0,Y.useValues)(ae({types:e})),{closeReorderTransformationsModal:s,setTemporaryTransformationOrder:d,saveTransformationsOrder:u}=(0,Y.useActions)(ae({types:e})),[E,c]=(0,Ue.useState)({}),K=o.filter(v=>v.stage==="transformation"&&v.enabled);(0,Ue.useEffect)(()=>{if(n){let v=K.reduce((T,M)=>({...T,[M.hog_function.id]:M.hog_function.execution_order||0}),{});c(v)}},[n,K]);let j=[...K];return Object.keys(r).length>0&&j.sort((v,T)=>{let M=r[v.hog_function.id]||0,z=r[T.hog_function.id]||0;return M-z}),(0,a.jsx)(Ne,{onClose:s,isOpen:n,width:600,title:"Reorder transformations",description:(0,a.jsxs)("p",{children:["The order of transformations is important as they are processed sequentially. You can"," ",(0,a.jsx)("b",{children:"drag and drop the transformations below"})," to change their order."]}),footer:(0,a.jsxs)(a.Fragment,{children:[(0,a.jsx)(y,{type:"secondary",onClick:s,children:"Cancel"}),(0,a.jsx)(y,{loading:i,type:"primary",onClick:()=>{let v=Object.entries(r).reduce((T,[M,z])=>E[M]!==z?{...T,[M]:z}:T,{});Object.keys(v).length>0?u(v):s()},children:"Save order"})]}),children:(0,a.jsx)("div",{className:"flex flex-col gap-2",children:(0,a.jsx)(Sn,{modifiers:[wn,An],onDragEnd:({active:v,over:T})=>{if(v.id&&T&&v.id!==T.id){let M=j.findIndex(l=>l.id===v.id),z=j.findIndex(l=>l.id===T.id),P=Tn(j,M,z).reduce((l,X,le)=>X.hog_function?.id?{...l,[X.hog_function.id]:le+1}:l,{});d(P)}},children:(0,a.jsx)(vn,{items:j,strategy:Ln,children:j.map((v,T)=>(0,a.jsx)(vt,{transformation:v,order:T},v.id))})})})})}var vt=({transformation:e,order:n})=>{let{attributes:o,listeners:r,setNodeRef:i,transform:s,transition:d,isDragging:u}=Nn({id:e.id});return(0,a.jsxs)("div",{ref:i,className:(0,ot.clsx)("relative flex items-center gap-2 p-2 border rounded cursor-move bg-bg-light",u&&"z-[999999]"),style:{transform:Pn.Transform.toString(s),transition:d},...o,...r,children:[(0,a.jsx)(pn.Number,{count:n+1,maxDigits:3}),(0,a.jsx)("span",{className:"font-semibold",children:e.name})]})};f();b();h();var Je=p(R());var oe=p(S());function it(){let{loading:e,importApps:n}=(0,Je.useValues)(be),{toggleEnabled:o,loadPluginConfigs:r}=(0,Je.useActions)(be);return(0,oe.jsx)(oe.Fragment,{children:(0,oe.jsx)(B,{dataSource:n,size:"small",loading:e,columns:[de(),me(),te(),fe(),{width:0,render:function(s,d){return(0,oe.jsx)(ee,{overlay:(0,oe.jsx)(Z,{items:[...ge(d,o,r)]})})}}]})})}f();b();h();f();b();h();var Ge=p(R());var Q=p(S());function We(){let{selfManagedTables:e}=(0,Ge.useValues)(he),{deleteSelfManagedTable:n,refreshSelfManagedTableSchema:o}=(0,Ge.useActions)(he);return(0,Q.jsx)(B,{dataSource:e,pagination:{pageSize:10},columns:[{width:0,render:(r,i)=>(0,Q.jsx)(Gn,{type:Jn(i.url_pattern)})},{title:"Source",dataIndex:"name",key:"name",render:(r,i)=>(0,Q.jsx)(we,{to:N.pipelineNode("source",`self-managed-${i.id}`,"source configuration"),title:i.name})},{key:"actions",render:(r,i)=>(0,Q.jsxs)("div",{className:"flex flex-row justify-end",children:[(0,Q.jsx)(y,{"data-attr":`refresh-data-warehouse-${i.name}`,onClick:()=>o(i.id),children:"Update schema from source"},`refresh-data-warehouse-${i.name}`),(0,Q.jsx)(y,{status:"danger","data-attr":`delete-data-warehouse-${i.name}`,onClick:()=>{ke.open({title:"Delete table?",description:"Table deletion cannot be undone. All views and joins related to this table will be deleted.",primaryButton:{children:"Delete",status:"danger",onClick:()=>{n(i.id)}},secondaryButton:{children:"Cancel"}})},children:"Delete"},`delete-data-warehouse-${i.name}`)]})}]})}var m=p(S());function at(){let e=[{label:"Source",to:N.pipelineNodeNew("source")},{label:"Transformation",to:N.pipelineNodeNew("transformation")},{label:"Destination",to:N.pipelineNodeNew("destination")}];return(0,m.jsxs)(m.Fragment,{children:[(0,m.jsx)(G,{buttons:(0,m.jsx)("div",{className:"flex items-center m-2 shrink-0",children:(0,m.jsx)(Ae,{items:e,children:(0,m.jsx)(y,{"data-attr":"new-pipeline-button",icon:(0,m.jsx)(gn,{}),size:"small",type:"primary",children:"New"})})})}),(0,m.jsxs)("div",{className:"space-y-4",children:[(0,m.jsxs)("div",{children:[(0,m.jsx)(k,{to:N.pipeline("sources"),children:(0,m.jsx)("h2",{children:"Managed sources"})}),(0,m.jsx)("div",{className:"space-y-2",children:(0,m.jsx)(De,{})})]}),(0,m.jsxs)("div",{children:[(0,m.jsx)(k,{to:N.pipeline("sources"),children:(0,m.jsx)("h2",{children:"Self-managed sources"})}),(0,m.jsx)("div",{className:"space-y-2",children:(0,m.jsx)(We,{})})]}),(0,m.jsxs)("div",{children:[(0,m.jsx)(k,{to:N.pipeline("transformations"),children:(0,m.jsx)("h2",{children:"Transformations"})}),(0,m.jsxs)("p",{children:["Modify and enrich your incoming data. Only active transformations are shown here."," ",(0,m.jsx)(k,{to:N.pipeline("transformations"),children:"See all."})]}),(0,m.jsx)(He,{types:Ee,hideFeedback:!0,hideAddDestinationButton:!1})]}),(0,m.jsxs)("div",{children:[(0,m.jsx)(k,{to:N.pipeline("destinations"),children:(0,m.jsx)("h2",{children:"Destinations"})}),(0,m.jsxs)("p",{children:["Send your data to destinations in real time or with batch exports. Only active Destinations are shown here. ",(0,m.jsx)(k,{to:N.pipeline("destinations"),children:"See all."})]}),(0,m.jsx)(He,{types:_e,hideFeedback:!0,hideAddDestinationButton:!1})]})]})]})}f();b();h();var H=p(R()),je=p(an());var en=e=>sn(e).replace(/[-_]/g," "),nn=(0,H.kea)([(0,H.path)(["scenes","pipeline","pipelineLogic"]),(0,H.connect)({values:[Oe,["user","hasAvailableFeature"]]}),(0,H.actions)({setCurrentTab:(e="destinations")=>({tab:e})}),(0,H.reducers)({currentTab:["destinations",{setCurrentTab:(e,{tab:n})=>n}]}),(0,H.selectors)(()=>({breadcrumbs:[e=>[e.currentTab],e=>[{key:"Pipeline",name:"Data pipeline"},{key:e,name:en(e)}]],[kn]:[()=>[],()=>({activity_scope:"Plugin"})]})),(0,je.actionToUrl)(({values:e})=>({setCurrentTab:()=>[N.pipeline(e.currentTab)]})),(0,je.urlToAction)(({actions:e,values:n})=>({"/pipeline/:tab":({tab:o})=>{o!==n.currentTab&&e.setCurrentTab(o)}}))]);f();b();h();var st=p(R());var _=p(S());function lt(){let{dataWarehouseSources:e,dataWarehouseSourcesLoading:n}=(0,st.useValues)(he);return(0,_.jsxs)(_.Fragment,{children:[(0,_.jsx)(G,{buttons:(0,_.jsx)(U,{stage:"source"})}),(0,_.jsxs)("div",{className:"space-y-4",children:[!n&&e?.results.length===0?(0,_.jsx)(q,{productName:"Data Warehouse Source",productKey:"data_warehouse",thingName:"data source",description:"Use data warehouse sources to import data from your external data into PostHog.",isEmpty:e.results.length===0&&!n,docsURL:"https://posthog.com/docs/data-warehouse",actionElementOverride:(0,_.jsx)(U,{stage:"source"})}):null,(0,_.jsxs)("div",{children:[(0,_.jsx)("h2",{children:"Managed sources"}),(0,_.jsx)("p",{children:"PostHog can connect to external sources and automatically import data from them into the PostHog data warehouse"}),(0,_.jsx)(De,{})]}),(0,_.jsxs)("div",{children:[(0,_.jsx)("h2",{children:"Self managed sources"}),(0,_.jsx)("p",{children:"Connect to your own data sources, making them queryable in PostHog"}),(0,_.jsx)(We,{})]})]})]})}f();b();h();var tn=p(R());var $=p(S());function pt(){let{sortedTransformations:e,loading:n}=(0,tn.useValues)(zn),o=e.length===0&&!n;return(0,$.jsxs)($.Fragment,{children:[(0,$.jsx)(G,{caption:"Transform your incoming events before they are stored in PostHog or sent on to Destinations.",buttons:(0,$.jsx)(U,{stage:"transformation"})}),(0,$.jsx)(q,{productName:"Pipeline transformations",thingName:"transformation",productKey:"pipeline_transformations",description:"Pipeline transformations allow you to enrich your data with additional information, such as geolocation.",docsURL:"https://posthog.com/docs/cdp",actionElementOverride:(0,$.jsx)(U,{stage:"transformation"}),isEmpty:o}),(0,$.jsx)(Te,{types:Ee})]})}var J=p(S());function kt(){let{canGloballyManagePlugins:e}=(0,Le.useValues)(ne),{currentTab:n}=(0,Le.useValues)(nn),{hasEnabledImportApps:o}=(0,Le.useValues)(be),{featureFlags:r}=(0,Le.useValues)(ln),i=[{key:"overview",content:(0,J.jsx)(at,{})},{key:"sources",content:(0,J.jsx)(lt,{})},{key:"transformations",content:(0,J.jsx)(pt,{})},{key:"destinations",content:(0,J.jsx)(Te,{types:_e})},{key:"site-apps",content:r[rn.SITE_APP_FUNCTIONS]?(0,J.jsx)(Te,{types:En}):(0,J.jsx)(Be,{})}];return o&&i.push({key:"legacy-sources",content:(0,J.jsx)(it,{})}),e&&i.push({key:"apps-management",content:(0,J.jsx)(Zn,{})}),i.push({key:"history",content:(0,J.jsx)(Un,{scope:["Plugin","PluginConfig","HogFunction"]})}),(0,J.jsx)("div",{className:"pipeline-scene",children:(0,J.jsx)(ce,{activeKey:n,onChange:s=>ut.router.actions.push(N.pipeline(s)),tabs:i.map(s=>({...s,label:en(s.key)}))})})}var Na={component:kt,logic:nn};export{kt as Pipeline,Na as scene};
//# sourceMappingURL=/static/Pipeline-2TTWWPBG.js.map
