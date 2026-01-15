import { useMDXComponents } from 'scenes/onboarding/OnboardingDocsContentWrapper'
import { StepDefinition } from '../steps'

export const getWebflowSteps = (CodeBlock: any, Markdown: any, dedent: any, snippets: any): StepDefinition[] => {
    const JSEventCapture = snippets?.JSEventCapture

    return [
        {
            title: 'Copy the web snippet',
            badge: 'required',
            content: (
                <>
                    <Markdown>First, copy your PostHog web snippet:</Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'html',
                                file: 'HTML',
                                code: dedent`
                                    <script>
                                        !function(t,e){var o,n,p,r;e.__SV||(window.posthog=e,e._i=[],e.init=function(i,s,a){function g(t,e){var o=e.split(".");2==o.length&&(t=t[o[0]],e=o[1]),t[e]=function(){t.push([e].concat(Array.prototype.slice.call(arguments,0)))}}(p=t.createElement("script")).type="text/javascript",p.async=!0,p.src=s.api_host.replace(".i.posthog.com","-assets.i.posthog.com")+"/static/array.js",(r=t.getElementsByTagName("script")[0]).parentNode.insertBefore(p,r);var u=e;for(void 0!==a?u=e[a]=[]:a="posthog",u.people=u.people||[],u.toString=function(t){var e="posthog";return"posthog"!==a&&(e+="."+a),t||(e+=" (stub)"),e},u.people.toString=function(){return u.toString(1)+".people (stub)"},o="init capture register register_once register_for_session unregister opt_out_capturing has_opted_out_capturing opt_in_capturing reset isFeatureEnabled getFeatureFlag getFeatureFlagPayload reloadFeatureFlags group identify setPersonProperties setPersonPropertiesForFlags resetPersonPropertiesForFlags setGroupPropertiesForFlags resetGroupPropertiesForFlags resetGroups onFeatureFlags addFeatureFlagsHandler onSessionId getSurveys getActiveMatchingSurveys renderSurvey canRenderSurvey getNextSurveyStep".split(" "),n=0;n<o.length;n++)g(u,o[n]);e._i.push([i,s,a])},e.__SV=1)}(document,window.posthog||[]);
                                        posthog.init('<ph_project_api_key>', {
                                            api_host: '<ph_client_api_host>',
                                            defaults: '2025-11-30'
                                        })
                                    </script>
                                `,
                            },
                        ]}
                    />
                </>
            ),
        },
        {
            title: 'Add to Webflow',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Go to your Webflow site settings by clicking on the menu icon in the top left. If you haven't
                        already, sign up for at least the **Basic** site plan. This enables you to add custom code. Then:
                    </Markdown>
                    <Markdown>
                        {`1. Go to the **Custom code** tab in site settings.
2. In the **Head code** section, paste your PostHog snippet and press save.
3. Publish your site.`}
                    </Markdown>
                </>
            ),
        },
        {
            title: 'Send events',
            content: <>{JSEventCapture && <JSEventCapture />}</>,
        },
    ]
}

export const WebflowInstallation = (): JSX.Element => {
    const { Steps, Step, CodeBlock, Markdown, dedent, snippets } = useMDXComponents()
    const steps = getWebflowSteps(CodeBlock, Markdown, dedent, snippets)

    return (
        <Steps>
            {steps.map((step, index) => (
                <Step key={index} title={step.title} badge={step.badge}>
                    {step.content}
                </Step>
            ))}
        </Steps>
    )
}
