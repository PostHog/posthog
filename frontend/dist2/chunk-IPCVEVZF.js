import{$d as P,Aa as ue,Ba as ge,C as j,D as re,E as le,F as se,G as pe,H as de,I as ce,Ip as he,Ko as $e,Oa as X,Oe as u,Pa as me,Sa as O,Ta as fe,a as ie,ad as Se,cc as L,ig as Fe,mi as w,pe as ye,r as A}from"/static/chunk-RFJTZKD6.js";import{a as Qe,z}from"/static/chunk-3UDJFOQH.js";import{d as _,e as C,g as V,j as G}from"/static/chunk-SJXEOBQC.js";C();G();V();var Re=_(ie());var a=_(A()),y="?utm_medium=in-product&utm_campaign=feature-flag",Z=`Remember to set a personal API key in the SDK to enable local evaluation.
`,E="Must initialize SDK with a personal API key to enable remote configuration.",k="Encrypted payloads are automatically decrypted on the server before being sent to the client.";function Ne({flagKey:t,groupType:e,multivariant:n,localEvaluation:r,payload:l,remoteConfiguration:s,encryptedPayload:m,samplePropertyName:S}){let p="await client.",d=l?"getFeatureFlagPayload":n?"getFeatureFlag":"isFeatureEnabled",g=S||"is_authorized";if(s){let I=E+(m?`
// ${k}`:"");return(0,a.jsx)(a.Fragment,{children:(0,a.jsx)(u,{language:"javascript",wrap:!0,children:`// ${I}
const remoteConfigPayload = await client.getRemoteConfigPayload('${t}')`})})}let c=r?e?`
        // add group properties used in the flag to ensure the flag
        // is evaluated locally, vs. going to our servers
        groupProperties: { ${e.group_type}: {'${g}': 'value', 'name': 'xyz'}}`:`
        // add person properties used in the flag to ensure the flag
        // is evaluated locally, vs. going to our servers
        personProperties: {'${g}': 'value'}`:"",h=e?`${p}${d}(
    '${t}',
    'user distinct id',${l?`
    undefined,`:""}
    {
        groups: { '${e.group_type}': '<${e.name_singular||"group"} ID>' },${c}
    }
)`:c?`${p}${d}(
    '${t}',
    'user distinct id',${l?`
    undefined,`:""}
    {${c}
    }
)`:`${p}${d}('${t}', 'user distinct id')`,f=l?"matchedFlagPayload":n?"enabledVariant":"isMyFlagEnabledForUser",b=n?`${f} === 'example-variant'`:`${f}`,$=l?"":`

if (${b}) {
    // Do something differently for this ${e?e.name_singular||"group":"user"}
}`;return(0,a.jsx)(a.Fragment,{children:(0,a.jsx)(u,{language:"javascript",wrap:!0,children:`${r?"// "+Z:""}const ${f} = ${h}${$}`})})}function xe({flagKey:t,groupType:e,multivariant:n,localEvaluation:r,samplePropertyName:l}){let s="PostHog::",m=n?"getFeatureFlag":"isFeatureEnabled",S=l||"is_authorized",p=r?e?`
    // empty person properties
    [],
    // add group properties used in the flag to ensure the flag
    // is evaluated locally, vs. going to our servers
    [${e.group_type} =>  ['${S}' => 'value', 'name' => 'xyz']]`:`
    // add person properties used in the flag to ensure the flag
    // is evaluated locally, vs. going to our servers
    ['${S}' => 'value']`:"",d=e?`${s}${m}(
    '${t}',
    'user distinct id',
    // group types
    ['${e.group_type}' => '<${e.name_singular||"group"} ID>'],${p}
)`:p?`${s}${m}(
    '${t}',
    'user distinct id',${p}
)`:`${s}${m}('${t}', 'user distinct id')`,g=n?"$enabledVariant":"$isMyFlagEnabledForUser",c=n?`${g} === 'example-variant'`:`${g}`;return(0,a.jsx)(a.Fragment,{children:(0,a.jsx)(u,{language:"php",wrap:!0,children:`${r?"// "+Z:""}${g} = ${d}

if (${c}) {
    // Do something differently for this ${e?e.name_singular||"group":"user"}
}`})})}function _e({flagKey:t,groupType:e,payload:n,remoteConfiguration:r,encryptedPayload:l,multivariant:s,localEvaluation:m,samplePropertyName:S}){let p="client.",d=n?"GetFeatureFlagPayload":s?"GetFeatureFlag":"IsFeatureEnabled",g=S||"is_authorized";if(r){let $=E+(l?`
// ${k}`:"");return(0,a.jsx)(a.Fragment,{children:(0,a.jsx)(u,{language:"go",wrap:!0,children:`// ${$}
remoteConfigPayload, err := ${p}GetRemoteConfigPayload("${t}")`})})}let c=m?e?`
        // add group properties used in the flag to ensure the flag
        // is evaluated locally, vs. going to our servers
        groupProperties: map[string]Properties{"${e.group_type}": posthog.NewProperties().Set("${g}", "value").Set("name", "xyz")}`:`
        // add person properties used in the flag to ensure the flag
        // is evaluated locally, vs. going to our servers
        PersonProperties: posthog.NewProperties().Set("${g}", "value")`:"",h=e?`${p}${d}(
    FeatureFlagPayload{
        Key:        "${t}",
        DistinctId: "distinct-id",
        Groups:     Groups{'${e.group_type}': '<${e.name_singular||"group"} ID>'},${c}
    }
)`:`${p}${d}(
    FeatureFlagPayload{
        Key:        '${t}',
        DistinctId: "distinct-id",${c}
    })`,f=s?"enabledVariant, err":"isMyFlagEnabledForUser, err",b=s?"enabledVariant == 'example-variant'":"isMyFlagEnabledForUser";return(0,a.jsx)(a.Fragment,{children:(0,a.jsx)(u,{language:"go",wrap:!0,children:`${m?"// "+Z:""}${f} := ${h}

if ${b} {
    // Do something differently for this ${e?e.name_singular||"group":"user"}
}`})})}function Ce({flagKey:t,groupType:e,multivariant:n,localEvaluation:r,payload:l,remoteConfiguration:s,encryptedPayload:m,samplePropertyName:S}){let p="posthog.",d=l?"get_feature_flag_payload":n?"get_feature_flag":"is_feature_enabled",g=S||"is_authorized";if(s){let I="# "+E+(m?`
# ${k}`:"");return(0,a.jsx)(a.Fragment,{children:(0,a.jsx)(u,{language:"ruby",wrap:!0,children:`${I}
remote_config_payload = posthog.get_remote_config_payload('${t}')`})})}let c=r?e?`
    # add group properties used in the flag to ensure the flag
    # is evaluated locally, vs. going to our servers
    group_properties: { ${e.group_type}: {'${g}': 'value', 'name': 'xyz'}}`:`
    # add person properties used in the flag to ensure the flag
    # is evaluated locally, vs. going to our servers
    person_properties: {'${g}': 'value'}`:"",h=e?`${p}${d}(
    '${t}',
    'user distinct id',
    groups: { '${e.group_type}': '<${e.name_singular||"group"} ID>' },${c}
)`:c?`${p}${d}(
    '${t}',
    'user distinct id',${c}
)`:`${p}${d}('${t}', 'user distinct id')`,f=l?"matched_flag_payload":n?"enabled_variant":"is_my_flag_enabled",b=n?`${f} == 'example-variant'`:`${f}`,$=l?"":`

if ${b}
    # Do something differently for this ${e?e.name_singular||"group":"user"}
end`;return(0,a.jsx)(a.Fragment,{children:(0,a.jsx)(u,{language:"ruby",wrap:!0,children:`${r?"# "+Z:""}${f} = ${h}${$}`})})}function Ve({flagKey:t,groupType:e,multivariant:n,localEvaluation:r,payload:l,remoteConfiguration:s,encryptedPayload:m,samplePropertyName:S}){let p="posthog.",d=l?"get_feature_flag_payload":n?"get_feature_flag":"feature_enabled",g=S||"is_authorized";if(s){let I="# "+E+(m?`
# ${k}`:"");return(0,a.jsx)(a.Fragment,{children:(0,a.jsx)(u,{language:"python",wrap:!0,children:`${I}
remote_config_payload = posthog.get_remote_config_payload('${t}')`})})}let c=r?e?`
    # add group properties used in the flag to ensure the flag
    # is evaluated locally, vs. going to our servers
    group_properties={ ${e.group_type}: {'${g}': 'value', 'name': 'xyz'}}`:`
    # add person properties used in the flag to ensure the flag
    # is evaluated locally, vs. going to our servers
    person_properties={'${g}': 'value'}`:"",h=e?`${p}${d}(
    '${t}',
    'user distinct id',
    groups={ '${e.group_type}': '<${e.name_singular||"group"} ID>' },${c}
)`:c?`${p}${d}(
    '${t}',
    'user distinct id',${c}
)`:`${p}${d}('${t}', 'user distinct id')`,f=l?"matched_flag_payload":n?"enabled_variant":"is_my_flag_enabled",b=n?`${f} == 'example-variant'`:`${f}`,$=l?"":`

if ${b}:
    # Do something differently for this ${e?e.name_singular||"group":"user"}
`;return(0,a.jsx)(a.Fragment,{children:(0,a.jsx)(u,{language:"python",wrap:!0,children:`${r?"# "+Z:""}${f} = ${h}${$}`})})}function Ge({flagKey:t,groupType:e,multivariant:n,localEvaluation:r,payload:l,remoteConfiguration:s,encryptedPayload:m,samplePropertyName:S}){let p="posthog.",d=l||n?"GetFeatureFlagAsync":"IsFeatureEnabledAsync",g=S||"isAuthorized";if(s){let v="// "+E+(m?`
// ${k}`:"");return(0,a.jsx)(a.Fragment,{children:(0,a.jsx)(u,{language:"csharp",wrap:!0,children:`${v}
var remoteConfigPayload = await posthog.GetRemoteConfigPayloadAsync("${t}");`})})}let c=r?e?`// add group properties used in the flag to ensure the flag
        // is evaluated locally, vs. going to our servers
        `:`// add person properties used in the flag to ensure the flag
        // is evaluated locally, vs. going to our servers
        `:"",h=r?e?`{ ["${g}"] = "value", ["name"] = "xyz" }`:`
    personProperties: new() { ["${g}"] = "value" }`:"",f=e?`await ${p}${d}(
    "${t}",
    "user distinct id",
    new FeatureFlagOptions
    {
        ${c}Groups = [new Group("${e.group_type}", "<${e.name_singular||"group"} ID>")${h}]
    }
);`:h?`await ${p}${d}(
    "${t}",
    "user distinct id",${h}
);`:`await ${p}${d}("${t}", "user distinct id");`,b=l?"matchedFlagPayload":n?"enabledVariant":"isMyFlagEnabled",$=n?`${b} == 'example-variant'`:`${b}`,I=l?`
if (matchedFlagPayload is { Payload: {} payload })
{
    // The payload is a JsonDocument.
    Console.WriteLine(payload.RootElement.GetRawText());
}`:`

if (${$}) {
    // Do something differently for this ${e?e.name_singular||"group":"user"}
}
`;return(0,a.jsx)(a.Fragment,{children:(0,a.jsx)(u,{language:"csharp",wrap:!0,children:`${r?"// "+Z:""}var ${b} = ${f}${I}`})})}function Ze({flagKey:t,multivariant:e,payload:n}){let r="PostHog.";if(n)return(0,a.jsx)(u,{language:"kotlin",wrap:!0,children:`${r}getFeatureFlagPayload("${t}")`});let l=e?"getFeatureFlag":"isFeatureEnabled",s=e?' == "example-variant"':"";return(0,a.jsx)(u,{language:"kotlin",wrap:!0,children:`if (${r}${l}("${t}")${s}) {
    // do something
}
            `})}function Ee({flagKey:t,multivariant:e,payload:n}){let r="await Posthog().";if(n)return(0,a.jsx)(u,{language:"dart",wrap:!0,children:`${r}getFeatureFlagPayload('${t}');`});let l=e?"getFeatureFlag":"isFeatureEnabled",s=e?" == 'example-variant'":"";return(0,a.jsx)(u,{language:"dart",wrap:!0,children:`if (${r}${l}('${t}')${s}) {
  // do something
}
            `})}function ke({flagKey:t,multivariant:e,payload:n}){let r="PostHogSDK.shared.";if(n)return(0,a.jsx)(u,{language:"swift",wrap:!0,children:`${r}getFeatureFlagPayload("${t}")`});let l=e?"getFeatureFlag":"isFeatureEnabled",s=e?'as? String == "example-variant"':"";return(0,a.jsx)(u,{language:"swift",wrap:!0,children:`if ${r}${l}("${t}")${s} {
    // do something
}`})}function We({flagKey:t,multivariant:e,payload:n}){let r="posthog.";if(n)return(0,a.jsx)(u,{language:"jsx",wrap:!0,children:`${r}getFeatureFlagPayload('${t}')`});let l=e?"getFeatureFlag":"isFeatureEnabled",s=e?" == 'example-variant'":"";return(0,a.jsx)(u,{language:"jsx",wrap:!0,children:`// With a hook
import { useFeatureFlag } from 'posthog-react-native'

const MyComponent = () => {
    const showFlaggedFeature = useFeatureFlag('${t}')

    if (showFlaggedFeature === undefined) {
        // the response is undefined if the flags are being loaded
        return null
    }

    return showFlaggedFeature ${s} ? <Text>Testing feature \u{1F604}</Text> : <Text>Not Testing feature \u{1F622}</Text>
}

// Or calling on the method directly
${r}${l}('${t}')
            `})}function Je({flagKey:t,multivariant:e,payload:n}){let r=n?"useFeatureFlagPayload":e?"useFeatureFlagVariantKey":"useFeatureFlagEnabled",l=n?"payload":e?"variant":"flagEnabled",s=e?" == 'example-variant'":"";return(0,a.jsx)(u,{language:"jsx",wrap:!0,children:`
import { ${r} } from 'posthog-js/react'

function App() {
    const ${l} = ${r}('${t}')

    if (${l}${s}) {
        // do something
    }
}`})}function Ae({flagKey:t,groupType:e,remoteConfiguration:n}){let{currentTeam:r}=(0,Re.useValues)($e),l=e?`,
    "groups": { "${e.group_type}": "<${e.name_singular||"group"} ID>" },`:"";return n?(0,a.jsx)(a.Fragment,{children:(0,a.jsx)(u,{language:"bash",wrap:!0,children:`curl ${w()}/api/projects/${r?.id||":projectId"}/feature_flags/${t||":featureFlagKey"}/remote_config/ \\
-H 'Content-Type: application/json' \\
-H 'Authorization: Bearer [personal_api_key]'`})}):(0,a.jsx)(a.Fragment,{children:(0,a.jsx)(u,{language:"bash",wrap:!0,children:`curl ${w()}/decide?v=3/ \\
-X POST -H 'Content-Type: application/json' \\
-d '{
    "api_key": "${r?r.api_token:"[project_api_key]"}",
    "distinct_id": "[user distinct id]"${l}
}'
                `})})}function Xe({flagKey:t,multivariant:e,payload:n,groupType:r,instantlyAvailableProperties:l,samplePropertyName:s}){if(n)return(0,a.jsx)(a.Fragment,{children:(0,a.jsx)(u,{language:"javascript",wrap:!0,children:`posthog.getFeatureFlagPayload('${t??""}')`})});let m=s||"is_authorized",S=`// Your flag depends on properties that are not instantly available. If you want
// to make them available without waiting for server delays, send these properties for flag evaluation, like so:
// Make sure to call this before evaluating flags. More info: https://posthog.com/docs/libraries/js#overriding-server-properties 
posthog.${r?`setGroupPropertiesForFlags({ '${r.group_type}': {'${m}': 'value'}})`:`setPersonPropertiesForFlags({'${m}': 'value'})`}

`,p="posthog.",d=e?"getFeatureFlag":"isFeatureEnabled",g=e?" == 'example-variant'":"";return(0,a.jsx)(a.Fragment,{children:(0,a.jsx)(u,{language:"javascript",wrap:!0,children:`${l?"":S}// Ensure flags are loaded before usage.
// You'll only need to call this on the code for when the first time a user visits.
${p}onFeatureFlags(function() {
    // feature flags should be available at this point
    if (${p}${d}('${t??""}') ${g}) {
        // do something
    }
})

// Otherwise, you can just do:
if (${p}${d}('${t??""}') ${g}) {
    // do something
}`})})}function Q(){return(0,a.jsx)(u,{language:"javascript",wrap:!0,children:`// Initialise the posthog library with a distinct ID and feature flags for immediate loading
// This avoids the delay between the library loading and feature flags becoming available to use.

posthog.init('{project_api_key}', {
    api_host: '${w()}'
    bootstrap:
    {
        distinctID: 'your-anonymous-id',
        featureFlags: {
    // input the flag values here from 'posthog.getAllFlags(distinct_id)' which you can find in the server-side libraries.
        // example:
            // 'flag-1': true,
            // 'variant-flag': 'control',
            // 'other-flag': false
        },
    }
})
            `})}C();G();V();var B=_(ie());var N=_(Qe());C();G();V();var F="https://posthog.com/docs/",Le="#feature-flags",Pe="#feature-flag-payloads",we="#local-evaluation",Oe="#bootstrapping-flags";var W=[{value:"JavaScript",documentationLink:`${F}libraries/js${y}`,Snippet:Xe,type:"Client",key:"javascript_web",Icon:j},{value:"Android",documentationLink:`${F}libraries/android${y}`,Snippet:Ze,type:"Client",key:"android",Icon:ge},{value:"API",documentationLink:`${F}api/post-only-endpoints#example-request--response-decide-v3`,Snippet:Ae,type:"Server",key:"api",Icon:Se},{value:"Go",documentationLink:`${F}libraries/go${y}`,Snippet:_e,type:"Server",key:"go",Icon:pe},{value:"Flutter",documentationLink:`${F}libraries/flutter${y}`,Snippet:Ee,type:"Client",key:"flutter",Icon:me},{value:"iOS",documentationLink:`${F}libraries/ios${y}`,Snippet:ke,type:"Client",key:"ios",Icon:ue},{value:"Node.js",documentationLink:`${F}libraries/node${y}`,Snippet:Ne,type:"Server",key:"nodejs",Icon:re},{value:"React",documentationLink:`${F}libraries/react${y}`,Snippet:Je,type:"Client",key:"react",Icon:X},{value:"React Native",documentationLink:`${F}libraries/react-native${y}`,Snippet:We,type:"Client",key:"react_native",Icon:X},{value:"PHP",documentationLink:`${F}libraries/php${y}`,Snippet:xe,type:"Server",key:"php",Icon:le},{value:"Python",documentationLink:`${F}libraries/python${y}`,Snippet:Ve,type:"Server",key:"python",Icon:de},{value:"Ruby",documentationLink:`${F}libraries/ruby${y}`,Snippet:Ce,type:"Server",key:"ruby",Icon:se},{value:"C#/.NET",documentationLink:`${F}libraries/dotnet${y}`,Snippet:Ge,type:"Server",key:"dotnet",Icon:ce}],K=["nodejs","python","ruby","php","go","dotnet"],Y=["api","javascript_web","nodejs","python","ruby","react","android","react_native","ios","flutter","dotnet","go"],Ye=["api","nodejs","python","go","ruby","dotnet"],U=[{value:"JavaScript",documentationLink:`${F}libraries/js${y}${Oe}`,Snippet:Q,type:"Client",key:"javascript_web",Icon:j},{value:"React Native",documentationLink:`${F}libraries/react-native${y}${Oe}`,Snippet:Q,type:"Client",key:"react_native",Icon:X}];var i=_(A());function qe({documentationLink:t}){return(0,i.jsxs)("div",{className:"mt-4",children:["Need more information?"," ",(0,i.jsx)(fe,{"data-attr":"feature-flag-doc-link",target:"_blank",to:t,targetBlankIcon:!0,children:"Check the docs"})]})}function et({options:t,selectedLanguage:e,featureFlag:n,dataAttr:r="",showLocalEval:l=!1,showBootstrap:s=!1,showAdvancedOptions:m=!0,showFooter:S=!0}){let p=n?.has_encrypted_payloads,d=n?.is_remote_configuration,[g]=(d?t.filter(o=>o.key==="nodejs"):t)||[t[0]],[c,h]=(0,N.useState)(g),[f,b]=(0,N.useState)(U[0]),[$,I]=(0,N.useState)(n?.is_remote_configuration||Object.keys(n?.filters.payloads||{}).length>0),[v,H]=(0,N.useState)(l),[J,q]=(0,N.useState)(s),Ue=!n?.is_remote_configuration,ee=!!n?.filters.multivariate?.variants,D=n?.key||"my-flag",{groupTypes:Be}=(0,B.useValues)(Fe),te=n?.filters?.aggregation_group_type_index!=null?Be.get(n.filters.aggregation_group_type_index):void 0,{reportFlagsCodeExampleInteraction:T,reportFlagsCodeExampleLanguage:He}=(0,B.useActions)(he),De=()=>{let o=c.documentationLink;if(J)return f.documentationLink;let R=Le;return v?R=we:$&&(R=Pe),`${o}${R}`},M=o=>{let R=t.find(x=>x.key===o);R&&h(R),Y.find(x=>x===o)||I(!1),K.find(x=>x===o)||H(!1);let oe=U.find(x=>x.key===o);oe?b(oe):q(!1)};(0,N.useEffect)(()=>{M(e||g.key),n?.is_remote_configuration||Object.keys(n?.filters.payloads||{}).length>0&&Object.values(n?.filters.payloads||{}).some(o=>o)?I(!0):I(!1),n?.ensure_experience_continuity&&H(!1)},[e,n]);let ae=n?.filters?.groups||[],ne=ae.find(o=>o.properties?.length&&o.properties.some(R=>!z.includes(R.key||"")))?.properties?.find(o=>!z.includes(o.key||""))?.key,Te=ae.find(o=>o.properties?.length)?.properties?.[0]?.key,Me=[{title:"Client libraries",options:W.filter(o=>o.type=="Client").map(o=>({value:o.key,label:o.value,"data-attr":`feature-flag-instructions-select-option-${o.key}`,labelInMenu:(0,i.jsxs)("div",{className:"flex items-center space-x-2",children:[(0,i.jsx)(o.Icon,{}),(0,i.jsx)("span",{children:o.value})]})}))},{title:"Server libraries",options:W.filter(o=>o.type=="Server").map(o=>({value:o.key,label:o.value,"data-attr":`feature-flag-instructions-select-option-${o.key}`,labelInMenu:(0,i.jsxs)("div",{className:"flex items-center space-x-2",children:[(0,i.jsx)(o.Icon,{}),(0,i.jsx)("span",{children:o.value})]})}))}],ze=[{title:"Server libraries",options:W.filter(o=>Ye.includes(o.key)).map(o=>({value:o.key,label:o.value,"data-attr":`feature-flag-instructions-select-option-${o.key}`,labelInMenu:(0,i.jsxs)("div",{className:"flex items-center space-x-2",children:[(0,i.jsx)(o.Icon,{}),(0,i.jsx)("span",{children:o.value})]})}))}],je=d?ze:Me;return(0,i.jsxs)("div",{children:[m&&(0,i.jsxs)("div",{className:"flex items-center gap-6",children:[(0,i.jsx)("div",{children:(0,i.jsx)(ye,{"data-attr":"feature-flag-instructions-select"+(r?`-${r}`:""),options:je,onChange:o=>{o&&(M(o),He(o))},value:c.key})}),(0,i.jsx)(O,{title:`Feature flag payloads are only available in these libraries: ${Y.map(o=>` ${o}`)}`,children:(0,i.jsxs)("div",{className:"flex items-center gap-1",children:[(0,i.jsx)(P,{label:"Show payload option",onChange:()=>{I(!$),T("payloads")},"data-attr":"flags-code-example-payloads-option",checked:$,disabled:!Y.includes(c.key)}),(0,i.jsx)(L,{className:"text-xl text-secondary shrink-0"})]})}),(0,i.jsxs)(i.Fragment,{children:[(0,i.jsx)(O,{title:`Bootstrapping is only available client side in our JavaScript and React Native
                                libraries.`,children:(0,i.jsxs)("div",{className:"flex items-center gap-1",children:[(0,i.jsx)(P,{label:"Show bootstrap option","data-attr":"flags-code-example-bootstrap-option",checked:J,onChange:()=>{q(!J),T("bootstrap")},disabled:!U.map(o=>o.key).includes(c.key)||!!n?.ensure_experience_continuity}),(0,i.jsx)(L,{className:"text-xl text-secondary shrink-0"})]})}),(0,i.jsx)(O,{title:`Local evaluation is only available in server side libraries and without flag
                                persistence.`,children:(0,i.jsxs)("div",{className:"flex items-center gap-1",children:[(0,i.jsx)(P,{label:"Show local evaluation option","data-attr":"flags-code-example-local-eval-option",checked:v,onChange:()=>{H(!v),T("local evaluation")},disabled:d||!K.includes(c.key)||!!n?.ensure_experience_continuity}),(0,i.jsx)(L,{className:"text-xl text-secondary shrink-0"})]})})]})]}),(0,i.jsxs)("div",{className:"mt-4 mb",children:[v&&(0,i.jsx)(i.Fragment,{children:(0,i.jsx)("h4",{className:"l4",children:"Local evaluation"})}),Ue&&(0,i.jsx)(c.Snippet,{"data-attr":"feature-flag-instructions-snippet",flagKey:D,multivariant:ee,groupType:te,localEvaluation:v,instantlyAvailableProperties:!ne,samplePropertyName:ne||Te}),$&&(0,i.jsxs)(i.Fragment,{children:[(0,i.jsx)("h4",{className:"l4",children:"Payload"}),(0,i.jsx)(c.Snippet,{"data-attr":"feature-flag-instructions-payload-snippet",flagKey:D,multivariant:ee,groupType:te,localEvaluation:v,payload:!0,remoteConfiguration:d,encryptedPayload:p})]}),J&&(0,i.jsxs)(i.Fragment,{children:[(0,i.jsx)("h4",{className:"l4",children:"Bootstrap"}),(0,i.jsx)(f.Snippet,{flagKey:D})]}),S&&(0,i.jsx)(qe,{documentationLink:De()})]}),(0,i.jsx)("div",{})]})}function Jt({featureFlag:t}){return(0,i.jsx)(et,{options:W,featureFlag:t})}export{y as a,W as b,et as c,Jt as d};
//# sourceMappingURL=/static/chunk-IPCVEVZF.js.map
