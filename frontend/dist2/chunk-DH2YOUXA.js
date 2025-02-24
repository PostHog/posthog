import{j as C}from"/static/chunk-CBJ7RAUW.js";import{Di as k,Gi as w,Hi as O,Lg as U,Sa as g,Ta as L,a as Q,cc as b,gg as A,ie as x,ig as E,ji as W,ki as M,pe as y,r as v,sl as I,tl as P,ul as T,vl as $,wl as _}from"/static/chunk-RFJTZKD6.js";import{Ha as S,Tb as F}from"/static/chunk-3UDJFOQH.js";import{d,e as m,g as h,j as f}from"/static/chunk-SJXEOBQC.js";m();f();h();m();f();h();var N=d(Q());var e=d(v()),D={actionsTaxonomicGroupTypes:["events","actions","data_warehouse"],propertiesTaxonomicGroupTypes:["event_properties","person_properties","event_feature_flags","cohorts","elements","session_properties","hogql_expression","data_warehouse_properties","data_warehouse_person_properties"]};function ue({value:t,onChange:i}){let{groupTypes:a,aggregationLabel:u}=(0,N.useValues)(E),{needsUpgradeForGroups:r,canStartUsingGroups:o}=(0,N.useValues)(A),n="person_id",c=[n],l=[{title:"Event Aggregation",options:[{value:n,label:"Unique users"}]}];return r||o?l[0].footer=(0,e.jsx)(k,{needsUpgrade:r}):Array.from(a.values()).forEach(p=>{c.push(`$group_${p.group_type_index}`),l[0].options.push({value:`$group_${p.group_type_index}`,label:`Unique ${u(p.group_type_index).plural}`})}),c.push("properties.$session_id"),l[0].options.push({value:"properties.$session_id",label:"Unique sessions"}),l[0].options.push({label:"Custom SQL expression",options:[{value:!t||c.includes(t)?"":t,label:(0,e.jsx)("span",{className:"font-mono",children:t}),labelInMenu:function({onSelect:R}){return(0,e.jsx)("div",{className:"w-120",style:{maxWidth:"max(60vw, 20rem)"},children:(0,e.jsx)(U,{onChange:R,value:t,placeholder:`Enter SQL expression, such as:
- distinct_id
- properties.$session_id
- concat(distinct_id, ' ', properties.$session_id)
- if(1 < 2, 'one', 'two')`})})}}]}),(0,e.jsxs)("div",{className:"flex items-center w-full gap-2",children:[(0,e.jsx)("span",{children:"Aggregating by"}),(0,e.jsx)(y,{className:"flex-1",value:t,onChange:i,options:l,dropdownMatchSelectWidth:!1})]})}function ce({funnelWindowInterval:t,funnelWindowIntervalUnit:i,onFunnelWindowIntervalChange:a,onFunnelWindowIntervalUnitChange:u}){let r=Object.keys(w).map(n=>({label:S(F(t??7,n,`${n}s`,!1)),value:n})),o=w[i??"day"];return(0,e.jsxs)("div",{className:"flex items-center gap-2",children:[(0,e.jsxs)("span",{className:"flex whitespace-nowrap",children:["Conversion window limit",(0,e.jsx)(g,{title:(0,e.jsxs)(e.Fragment,{children:[(0,e.jsx)("b",{children:"Recommended!"})," Limit to participants that converted within a specific time frame. Participants that do not convert in this time frame will be considered as drop-offs."]}),children:(0,e.jsx)(b,{className:"w-4 info-indicator"})})]}),(0,e.jsxs)("div",{className:"flex items-center gap-2",children:[(0,e.jsx)(x,{type:"number",className:"max-w-20",fullWidth:!1,min:o[0],max:o[1],value:t,onChange:a}),(0,e.jsx)(y,{dropdownMatchSelectWidth:!1,value:i,onChange:u,options:r})]})]})}function de({value:t,onChange:i,stepsLength:a}){return(0,e.jsxs)("div",{className:"flex items-center w-full gap-2",children:[(0,e.jsxs)("div",{className:"flex",children:[(0,e.jsx)("span",{children:"Attribution type"}),(0,e.jsx)(g,{closeDelayMs:200,title:(0,e.jsxs)("div",{className:"space-y-2",children:[(0,e.jsx)("div",{children:"When breaking down funnels, it's possible that the same properties don't exist on every event. For example, if you want to break down by browser on a funnel that contains both frontend and backend events."}),(0,e.jsx)("div",{children:"In this case, you can choose from which step the properties should be selected from by modifying the attribution type. There are four modes to choose from:"}),(0,e.jsxs)("ul",{className:"list-disc pl-4",children:[(0,e.jsx)("li",{children:"First touchpoint: the first property value seen in any of the steps is chosen."}),(0,e.jsx)("li",{children:"Last touchpoint: the last property value seen from all steps is chosen."}),(0,e.jsx)("li",{children:"All steps: the property value must be seen in all steps to be considered in the funnel."}),(0,e.jsx)("li",{children:"Specific step: only the property value seen at the selected step is chosen."})]}),(0,e.jsxs)("div",{children:["Read more in the"," ",(0,e.jsx)(L,{to:"https://posthog.com/docs/product-analytics/funnels#attribution-types",children:"documentation."})]})]}),children:(0,e.jsx)(b,{className:"text-xl text-secondary shrink-0 ml-1"})})]}),(0,e.jsx)(y,{value:t,placeholder:"Attribution",options:[{value:"first_touch",label:"First touchpoint"},{value:"last_touch",label:"Last touchpoint"},{value:"all_events",label:"All steps"},{value:"step",label:"Any step",hidden:"unordered"!==void 0},{label:"Specific step",options:Array(O).fill(null).map((r,o)=>({value:`step/${o}`,label:`Step ${o+1}`,hidden:o>=a})),hidden:"unordered"===void 0}],onChange:i,dropdownMaxContentWidth:!0,"data-attr":"breakdown-attributions"})]})}var s=d(v()),V=[{key:"timestamp_field",label:"Timestamp Field"},{key:"data_warehouse_join_key",label:"Data Warehouse Join Key",allowHogQL:!0},{key:"events_join_key",label:"Events Join Key",allowHogQL:!0,hogQLOnly:!0,tableName:"events"}];function Fe({metric:t,handleSetMetric:i}){let a=$(t.metric_type),u=_(t.metric_type),r=t.metric_config.kind==="ExperimentDataWarehouseMetricConfig";return(0,s.jsxs)("div",{className:"space-y-4",children:[(0,s.jsxs)("div",{children:[(0,s.jsx)("h4",{className:"mb-2",children:"Metric type"}),(0,s.jsx)(M,{"data-attr":"metrics-selector",value:t.metric_type,onChange:o=>{let n=_(o);i({newMetric:{...t,metric_type:o,metric_config:{...t.metric_config,math:n[0]}}})},options:[{value:"binomial",label:"Binomial",description:"Tracks whether an event happens for each user, useful for measuring conversion rates."},{value:"count",label:"Count",description:"Tracks how many times an event happens, useful for click counts or page views."},{value:"continuous",label:"Continuous",description:"Measures numerical values like revenue or session length."}]})]}),(0,s.jsx)(W,{bordered:!0,filters:I(t.metric_config),setFilters:({actions:o,events:n,data_warehouse:c})=>{let l=n?.[0]||o?.[0]||c?.[0],p=P(l);p&&i({newMetric:{...t,metric_config:p}})},typeKey:"experiment-metric",buttonCopy:"Add graph series",showSeriesIndicator:!1,hideRename:!0,entitiesLimit:1,showNumericalPropsOnly:!0,mathAvailability:a,allowedMathTypes:u,dataWarehousePopoverFields:V,...D}),(t.metric_type==="count"||t.metric_type==="continuous")&&!r&&(0,s.jsx)(C,{query:{kind:"InsightVizNode",source:T(t),showTable:!1,showLastComputation:!0,showLastComputationRefresh:!1},readOnly:!0}),t.metric_type==="binomial"&&!r&&(0,s.jsx)(C,{query:{kind:"InsightVizNode",source:T(t),showTable:!1,showLastComputation:!0,showLastComputationRefresh:!1},readOnly:!0})]})}export{D as a,ue as b,ce as c,de as d,Fe as e};
//# sourceMappingURL=/static/chunk-DH2YOUXA.js.map
