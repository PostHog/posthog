import{a as P,b,c as S,d as K,e as W,f}from"/static/chunk-CIEHRPUV.js";import{Io as L,Ko as w,Wd as A,Za as E,a as y,r as D,rp as C}from"/static/chunk-TW5IU73S.js";import{sc as v}from"/static/chunk-3UDJFOQH.js";import{d as u,e as V,g,j as h}from"/static/chunk-SJXEOBQC.js";V();h();g();var k=u(y());V();h();g();var s=u(y()),B=u(E());var N=1e3*60*60*6,T=(0,s.kea)([(0,s.props)({teamId:null}),(0,s.key)(({teamId:e})=>e||"no-team-id"),(0,s.path)(e=>["components","VersionChecker","versionCheckerLogic",e]),(0,s.actions)({setVersionWarning:e=>({versionWarning:e}),setSdkVersions:e=>({sdkVersions:e})}),(0,B.loaders)(({values:e})=>({availableVersions:[{},{loadAvailableVersions:async()=>{let r=fetch("https://api.github.com/repos/posthog/posthog-js/tags").then(a=>a.json()).then(a=>a.map(m=>b(m.name)).filter(v)),l=fetch("https://raw.githubusercontent.com/PostHog/posthog-js/main/deprecation.json").then(a=>a.json()),i=await Promise.allSettled([r,l]),n=i[0].status==="fulfilled"?i[0].value:[],d=i[1].status==="fulfilled"?i[1].value:{};return{...e.availableVersions,sdkVersions:n,deprecation:d}}}],usedVersions:[null,{loadUsedVersions:async()=>{let r={kind:"HogQLQuery",query:C`SELECT properties.$lib_version AS lib_version, max(timestamp) AS latest_timestamp, count(lib_version) as count
                                FROM events
                                WHERE timestamp >= now() - INTERVAL 1 DAY 
                                AND timestamp <= now()
                                AND properties.$lib = 'web'
                                GROUP BY lib_version
                                ORDER BY latest_timestamp DESC
                                limit 10`};return(await L.query(r,void 0,void 0,!0)).results?.map(i=>{let n=b(i[0]);return n?{version:n,timestamp:i[1]}:null}).filter(v)??null}}]})),(0,s.reducers)({lastCheckTimestamp:[0,{persist:!0},{loadUsedVersionsSuccess:()=>Date.now()}],versionWarning:[null,{persist:!0,prefix:"2024-02-12"},{setVersionWarning:(e,{versionWarning:r})=>r}]}),(0,s.sharedListeners)(({values:e,actions:r})=>({checkForVersionWarning:()=>{if(!e.usedVersions?.length)return;let{deprecation:l,sdkVersions:i}=e.availableVersions,n=K(e.usedVersions.map(o=>o.version)),d=i?.[0],a=l?.deprecateBeforeVersion?P(l.deprecateBeforeVersion):null,m=null;if(a){let o=S(a,n);o&&o.diff>0&&(m={latestUsedVersion:f(n),latestAvailableVersion:f(d||a),level:"error"})}if(!m&&i&&d){let o=S(d,n);if(o&&o.diff>0){let c=i.findIndex(U=>W(U,n));c===-1&&(c=i.length-1),c<o.diff&&(c=o.diff);let p;o.kind==="major"?p="info":o.kind==="minor"&&(p=c>=40?"warning":void 0),p===void 0&&c>=50&&(p="error"),p&&f(n).trim().length&&(m={latestUsedVersion:f(n),latestAvailableVersion:f(d),level:p,numVersionsBehind:c})}}r.setVersionWarning(m)}})),(0,s.listeners)(({sharedListeners:e})=>({loadAvailableVersionsSuccess:e.checkForVersionWarning,loadUsedVersionsSuccess:e.checkForVersionWarning})),(0,s.afterMount)(({actions:e,values:r})=>{r.lastCheckTimestamp<Date.now()-N&&(e.loadAvailableVersions(),e.loadUsedVersions())})]);var t=u(D());function ee(){let{currentTeamId:e}=(0,k.useValues)(w),{versionWarning:r}=(0,k.useValues)(T({teamId:e}));if(!r)return null;let l=`version-checker-${r.latestAvailableVersion}-${r.latestUsedVersion}`;return(0,t.jsxs)(A,{type:r.level,dismissKey:l,action:{children:"Update now",to:"https://posthog.com/docs/libraries/js#option-2-install-via-npm",targetBlank:!0},className:"mb-4",children:[(0,t.jsx)("b",{children:"Your PostHog SDK needs updating."})," The latest version of ",(0,t.jsx)("code",{children:"posthog-js"})," is"," ",(0,t.jsx)("b",{children:r.latestAvailableVersion}),", but you're using ",(0,t.jsx)("b",{children:r.latestUsedVersion}),"."," ",(0,t.jsx)("br",{}),r.level==="error"?(0,t.jsx)(t.Fragment,{children:"If something is not working as expected, try updating the SDK to the latest version where new features and bug fixes are available."}):void 0]})}export{ee as a};
//# sourceMappingURL=/static/chunk-4ZIAUDQ2.js.map
