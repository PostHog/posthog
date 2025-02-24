import{c as g,e as v}from"/static/chunk-B2IEXZN7.js";import{Do as o,Eo as l,Io as f,Xa as c,Za as T,a as w,f as b,sg as y}from"/static/chunk-TW5IU73S.js";import{d as s,e as D,g as d,j as m}from"/static/chunk-SJXEOBQC.js";D();m();d();var e=s(w()),E=s(T()),p=s(b());var u=i=>({id:"new",name:`New ${i?"Event":"Event property"}`}),z=(0,e.kea)([(0,e.path)(["scenes","data-management","definition","definitionViewLogic"]),(0,e.props)({}),(0,e.key)(i=>i.id||"new"),(0,e.actions)({setDefinition:(i,n={})=>({definition:i,options:n}),loadDefinition:i=>({id:i}),setDefinitionMissing:!0}),(0,e.connect)(()=>({values:[l,["hasAvailableFeature"]]})),(0,e.reducers)(()=>({definitionMissing:[!1,{setDefinitionMissing:()=>!0}]})),(0,E.loaders)(({values:i,actions:n})=>({definition:[u(i.isEvent),{setDefinition:({definition:t,options:{merge:a}})=>a?{...i.definition,...t}:t,loadDefinition:async({id:t},a)=>{let r={...i.definition};try{i.isEvent?r=await f.eventDefinitions.get({eventDefinitionId:t}):(r=await f.propertyDefinitions.get({propertyDefinitionId:t}),y({[`event/${r.name}`]:r})),a()}catch(P){throw n.setDefinitionMissing(),P}return r},deleteDefinition:async()=>(i.isEvent?await f.eventDefinitions.delete({eventDefinitionId:i.definition.id}):await f.propertyDefinitions.delete({propertyDefinitionId:i.definition.id}),p.router.actions.push(i.isEvent?o.eventDefinitions():o.propertyDefinitions()),i.isEvent?g.findMounted()?.actions.loadEventDefinitions():v.findMounted()?.actions.loadPropertyDefinitions(),i.definition)}]})),(0,e.selectors)({hasTaxonomyFeatures:[i=>[i.hasAvailableFeature],i=>i("ingestion_taxonomy")||i("tagging")],isEvent:[()=>[p.router.selectors.location],({pathname:i})=>i.includes(o.eventDefinitions())],isProperty:[i=>[i.isEvent],i=>!i],singular:[i=>[i.isEvent],i=>i?"event":"property"],breadcrumbs:[i=>[i.definition,i.isEvent],(i,n)=>[{key:"DataManagement",name:"Data management",path:n?o.eventDefinitions():o.propertyDefinitions()},{key:n?"events":"properties",name:n?"Events":"Properties",path:n?o.eventDefinitions():o.propertyDefinitions()},{key:[n?"EventDefinition":"PropertyDefinition",i?.id||"new"],name:i?.id!=="new"&&c(i?.name,n?"events":"event_properties")||"Untitled"}]]}),(0,e.afterMount)(({actions:i,values:n,props:t})=>{!t.id||t.id==="new"?i.setDefinition(u(n.isEvent)):i.loadDefinition(t.id)})]);export{z as a};
//# sourceMappingURL=/static/chunk-TBIQSJ6Q.js.map
