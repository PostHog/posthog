import{Aa as J,Ba as N,C as y,D as I,E as P,F as x,G as L,H as C,Oe as i,Pa as E,Ta as v,pe as w,r as S}from"/static/chunk-RFJTZKD6.js";import{a as j}from"/static/chunk-3UDJFOQH.js";import{d as u,e as c,g as m,j as f}from"/static/chunk-SJXEOBQC.js";c();f();m();var F=u(j());c();f();m();var e=u(S());function g(){return(0,e.jsx)("div",{className:"warning",children:(0,e.jsxs)("p",{children:[(0,e.jsx)("b",{children:"Warning:"})," Server side experiment metrics require you to manually send the feature flag information."," ",(0,e.jsx)(v,{to:"https://posthog.com/tutorials/experiments#step-2-sending-the-right-events",target:"_blank",children:"See this tutorial for more information."})]})})}function _({flagKey:t,variant:a}){return(0,e.jsx)(e.Fragment,{children:(0,e.jsx)(i,{language:"kotlin",wrap:!0,children:`if (PostHog.getFeatureFlag("${t}") == "${a}") {
    // do something
} else {
    // It's a good idea to let control variant always be the default behaviour,
    // so if something goes wrong with flag evaluation, you don't break your app.
}`})})}function O({flagKey:t,variant:a}){return(0,e.jsx)(e.Fragment,{children:(0,e.jsx)(i,{language:"swift",wrap:!0,children:`if (PostHogSDK.shared.getFeatureFlag("${t}") as? String == "${a}") {
    // do something
} else {
    // It's a good idea to let control variant always be the default behaviour,
    // so if something goes wrong with flag evaluation, you don't break your app.
}`})})}function T({flagKey:t,variant:a}){return(0,e.jsxs)(e.Fragment,{children:[(0,e.jsx)(i,{language:"javascript",wrap:!0,children:`const experimentFlagValue = await client.getFeatureFlag('${t}', 'user distinct id')

if (experimentFlagValue === '${a}' ) {
    // Do something differently for this user
} else {
    // It's a good idea to let control variant always be the default behaviour,
    // so if something goes wrong with flag evaluation, you don't break your app.
}`}),(0,e.jsx)(g,{})]})}function V({flagKey:t,variant:a}){return(0,e.jsxs)("div",{children:[(0,e.jsx)(i,{language:"javascript",wrap:!0,children:`if (posthog.getFeatureFlag('${t}') === '${a}') {
    // Do something differently for this user
} else {
    // It's a good idea to let control variant always be the default behaviour,
    // so if something goes wrong with flag evaluation, you don't break your app.
}`}),(0,e.jsx)("div",{className:"mt-4 mb-1",children:(0,e.jsx)("b",{children:"Test that it works"})}),(0,e.jsx)(i,{language:"javascript",wrap:!0,children:`posthog.featureFlags.overrideFeatureFlags({ flags: {'${t}': '${a}'} })`})]})}function D({flagKey:t,variant:a}){return(0,e.jsx)(e.Fragment,{children:(0,e.jsx)(i,{language:"javascript",wrap:!0,children:`// You can either use the useFeatureFlagVariantKey hook,
// or you can use the feature flags component - https://posthog.com/docs/libraries/react#feature-flags-react-component

// Method one: using the useFeatureFlagVariantKey hook
import { useFeatureFlagVariantKey } from 'posthog-js/react'

function App() {
    const variant = useFeatureFlagVariantKey('${t}')
    if (variant === '${a}') {
        // do something
    }
}

// Method two: using the feature flags component
import { PostHogFeature } from 'posthog-js/react'

function App() {
    return (
        <PostHogFeature flag='${t}' match='${a}'>
            <div>
                {/* the component to show */}
            </div>
        </PostHogFeature>
    )
}

// You can also test your code by overriding the feature flag:
posthog.featureFlags.overrideFeatureFlags({ flags: {'${t}': '${a}'} })`})})}function R({flagKey:t,variant:a}){return(0,e.jsx)(e.Fragment,{children:(0,e.jsx)(i,{language:"javascript",wrap:!0,children:`if (posthog.getFeatureFlag('${t}') === '${a}') {
    // Do something differently for this user
} else {
    // It's a good idea to let control variant always be the default behaviour,
    // so if something goes wrong with flag evaluation, you don't break your app.
}`})})}function A({flagKey:t,variant:a}){return(0,e.jsxs)(e.Fragment,{children:[(0,e.jsx)(i,{language:"php",wrap:!0,children:`if (PostHog::getFeatureFlag('${t}', 'user distinct id') == '${a}') {
    // Do something differently for this user
} else {
    // It's a good idea to let control variant always be the default behaviour,
    // so if something goes wrong with flag evaluation, you don't break your app.
}`}),(0,e.jsx)(g,{})]})}function H({flagKey:t,variant:a}){return(0,e.jsxs)(e.Fragment,{children:[(0,e.jsx)(i,{language:"go",wrap:!0,children:`experimentFlagValue, err := client.GetFeatureFlag(
                    FeatureFlagPayload{
                        Key:        '${t}',
                        DistinctId: "distinct-id",
                    })

if (experimentFlagValue == '${a}' ) {
    // Do something differently for this user
} else {
    // It's a good idea to let control variant always be the default behaviour,
    // so if something goes wrong with flag evaluation, you don't break your app.
}`}),(0,e.jsx)(g,{})]})}function X({flagKey:t,variant:a}){let n="await Posthog().",r="getFeatureFlag",b=` == '${a}'`;return(0,e.jsx)(e.Fragment,{children:(0,e.jsx)(i,{language:"dart",wrap:!0,children:`if (${n}${r}('${t}')${b}) {
  // Do something differently for this user
} else {
  // It's a good idea to let control variant always be the default behaviour,
  // so if something goes wrong with flag evaluation, you don't break your app.
}
            `})})}function G({flagKey:t,variant:a}){return(0,e.jsxs)(e.Fragment,{children:[(0,e.jsx)(i,{language:"ruby",wrap:!0,children:`experimentFlagValue = posthog.get_feature_flag('${t}', 'user distinct id')


if experimentFlagValue == '${a}'
    # Do something differently for this user
else
    # It's a good idea to let control variant always be the default behaviour,
    # so if something goes wrong with flag evaluation, you don't break your app.
end
`}),(0,e.jsx)(g,{})]})}function K({flagKey:t,variant:a}){return(0,e.jsxs)(e.Fragment,{children:[(0,e.jsx)(i,{language:"python",wrap:!0,children:`experiment_flag_value = posthog.get_feature_flag("${t}", "user_distinct_id"):

if experiment_flag_value == '${a}':
    # Do something differently for this user
else:
    # It's a good idea to let control variant always be the default behaviour,
    # so if something goes wrong with flag evaluation, you don't break your app.
`}),(0,e.jsx)(g,{})]})}var o=u(S()),p="?utm_medium=in-product&utm_campaign=experiment",l="https://posthog.com/docs/",s="#feature-flags";var h=[{value:"JavaScript",key:"javascript_web",documentationLink:`${l}libraries/js${p}${s}`,Icon:y,Snippet:V,type:"Client"},{value:"Android",key:"android",documentationLink:`${l}libraries/android${p}${s}`,Icon:N,Snippet:_,type:"Client"},{value:"Go",key:"go",documentationLink:`${l}libraries/go${p}${s}`,Icon:L,Snippet:H,type:"Server"},{value:"Flutter",key:"flutter",documentationLink:`${l}libraries/flutter${p}${s}`,Icon:E,Snippet:X,type:"Client"},{value:"iOS",key:"ios",documentationLink:`${l}libraries/ios${p}${s}`,Icon:J,Snippet:O,type:"Client"},{value:"Node.js",key:"nodejs",documentationLink:`${l}libraries/node${p}${s}`,Icon:I,Snippet:T,type:"Server"},{value:"PHP",key:"php",documentationLink:`${l}libraries/php${p}${s}`,Icon:P,Snippet:A,type:"Server"},{value:"Python",key:"python",documentationLink:`${l}libraries/python${p}${s}`,Icon:C,Snippet:K,type:"Server"},{value:"React",key:"react",documentationLink:`${l}libraries/react${p}${s}`,Icon:y,Snippet:D,type:"Client"},{value:"ReactNative",key:"react_native",documentationLink:`${l}libraries/react-native${p}${s}`,Icon:y,Snippet:R,type:"Client"},{value:"Ruby",key:"ruby",documentationLink:`${l}libraries/ruby${p}${s}`,Icon:x,Snippet:G,type:"Server"}];function q({selectedOptionValue:t,selectOption:a}){return(0,o.jsx)(w,{size:"small",className:"min-w-[7.5rem]",onSelect:a,value:t,options:[{title:"Client libraries",options:h.filter(n=>n.type=="Client").map(({Icon:n,value:r})=>({value:r,label:r,labelInMenu:(0,o.jsxs)("div",{className:"flex items-center space-x-2",children:[(0,o.jsx)(n,{}),(0,o.jsx)("span",{children:r})]})}))},{title:"Server libraries",options:h.filter(n=>n.type=="Server").map(({Icon:n,value:r})=>({value:r,label:r,labelInMenu:(0,o.jsxs)("div",{className:"flex items-center space-x-2",children:[(0,o.jsx)(n,{}),(0,o.jsx)("span",{children:r})]})}))}]})}function de({experiment:t}){let a=t?.parameters?.feature_flag_variants?.[1]?.key??"test",[n,r]=(0,F.useState)(a),[b]=h,[$,M]=(0,F.useState)(b),U=d=>{let k=h.find(Y=>Y.value===d);k&&M(k)};return(0,o.jsxs)("div",{className:"mb-4",children:[(0,o.jsx)("h2",{className:"font-semibold text-lg mb-2",children:"Implementation"}),(0,o.jsx)("div",{className:"border rounded bg-surface-primary",children:(0,o.jsxs)("div",{className:"p-6 space-y-4",children:[(0,o.jsxs)("div",{className:"flex justify-between",children:[(0,o.jsxs)("div",{className:"flex items-center",children:[(0,o.jsx)("span",{className:"mr-2",children:"Variant group"}),(0,o.jsx)(w,{size:"small",className:"min-w-[5rem]",onSelect:r,value:n,options:(t?.parameters?.feature_flag_variants||[]).map(d=>({value:d.key,label:d.key}))})]}),(0,o.jsx)("div",{children:(0,o.jsx)(q,{selectOption:U,selectedOptionValue:$.value})})]}),(0,o.jsxs)("div",{children:[(0,o.jsx)("div",{className:"mb-1",children:(0,o.jsx)("b",{children:"Implement your experiment in code"})}),(0,o.jsx)("div",{className:"mb-1",children:(0,o.jsx)($.Snippet,{variant:n,flagKey:t?.feature_flag?.key??""})}),(0,o.jsx)(v,{subtle:!0,to:$.documentationLink,target:"_blank",children:"See the docs for more implementation information."})]})]})})]})}export{h as a,de as b};
//# sourceMappingURL=/static/chunk-2D47HF5T.js.map
