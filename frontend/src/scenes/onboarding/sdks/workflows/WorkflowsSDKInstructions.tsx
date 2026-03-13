import {
    APIInstallation,
    AndroidInstallation,
    AngularInstallation,
    AstroInstallation,
    BubbleInstallation,
    DjangoInstallation,
    DocusaurusInstallation,
    ElixirInstallation,
    FlutterInstallation,
    FramerInstallation,
    GoInstallation,
    GoogleTagManagerInstallation,
    HTMLSnippetInstallation,
    HeliconeInstallation,
    IOSInstallation,
    JSWebInstallation,
    LangfuseInstallation,
    LaravelInstallation,
    MoEngageInstallation,
    N8nInstallation,
    NextJSInstallation,
    NodeJSInstallation,
    NuxtInstallation,
    PHPInstallation,
    PythonInstallation,
    ReactInstallation,
    ReactNativeInstallation,
    RemixInstallation,
    RetoolInstallation,
    RubyInstallation,
    RudderstackInstallation,
    SegmentInstallation,
    SentryInstallation,
    ShopifyInstallation,
    SvelteInstallation,
    TanStackInstallation,
    TraceloopInstallation,
    VueInstallation,
    WebflowInstallation,
    WordpressInstallation,
    ZapierInstallation,
} from '@posthog/shared-onboarding/product-analytics'
import { StepDefinition } from '@posthog/shared-onboarding/steps'

import { useMDXComponents } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { SDKInstructionsMap, SDKKey, SDKTag, SDKTagOverrides } from '~/types'

import { withOnboardingDocsWrapper } from '../shared/onboardingWrappers'

const SEND_EVENT_TITLES = ['Send events', 'Send an event', 'Send events via the API']

const WorkflowsFinalStepContent = (): JSX.Element => {
    const { Markdown, dedent } = useMDXComponents()
    return (
        <Markdown>
            {dedent`
                Now that PostHog is installed, any captured or custom event can be used as a [workflow trigger](https://posthog.com/docs/workflows/workflow-builder#triggers) to send **emails**, **Slack messages**, **SMS via Twilio**, or call **webhooks**.

                To get started, [configure a channel](/workflows/channels) then head to the [workflow builder](/workflows) to create your first automation.
            `}
        </Markdown>
    )
}

function workflowsModifySteps(steps: StepDefinition[]): StepDefinition[] {
    const installationSteps = steps.filter((step) => !SEND_EVENT_TITLES.includes(step.title))
    return [
        ...installationSteps,
        {
            title: 'Set up workflows',
            badge: 'recommended',
            content: <WorkflowsFinalStepContent />,
        },
    ]
}

// JS Web SDKs
const WorkflowsJSWebInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: JSWebInstallation,
    modifySteps: workflowsModifySteps,
})
const WorkflowsHTMLSnippetInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: HTMLSnippetInstallation,
    modifySteps: workflowsModifySteps,
})

// Frontend frameworks
const WorkflowsReactInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: ReactInstallation,
    modifySteps: workflowsModifySteps,
})
const WorkflowsNextJSInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: NextJSInstallation,
    modifySteps: workflowsModifySteps,
})
const WorkflowsSvelteInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: SvelteInstallation,
    modifySteps: workflowsModifySteps,
})
const WorkflowsAstroInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: AstroInstallation,
    modifySteps: workflowsModifySteps,
})
const WorkflowsTanStackInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: TanStackInstallation,
    modifySteps: workflowsModifySteps,
})
const WorkflowsAngularInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: AngularInstallation,
    modifySteps: workflowsModifySteps,
})
const WorkflowsVueInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: VueInstallation,
    modifySteps: workflowsModifySteps,
})
const WorkflowsNuxtJSInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: NuxtInstallation,
    modifySteps: workflowsModifySteps,
})
const WorkflowsRemixJSInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: RemixInstallation,
    modifySteps: workflowsModifySteps,
})

// Website builders
const WorkflowsBubbleInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: BubbleInstallation,
    modifySteps: workflowsModifySteps,
})
const WorkflowsFramerInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: FramerInstallation,
    modifySteps: workflowsModifySteps,
})
const WorkflowsWebflowInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: WebflowInstallation,
    modifySteps: workflowsModifySteps,
})
const WorkflowsDocusaurusInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: DocusaurusInstallation,
    modifySteps: workflowsModifySteps,
})
const WorkflowsGoogleTagManagerInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: GoogleTagManagerInstallation,
    modifySteps: workflowsModifySteps,
})
const WorkflowsShopifyInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: ShopifyInstallation,
    modifySteps: workflowsModifySteps,
})
const WorkflowsWordpressInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: WordpressInstallation,
    modifySteps: workflowsModifySteps,
})
const WorkflowsRetoolInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: RetoolInstallation,
    modifySteps: workflowsModifySteps,
})

// Mobile SDKs
const WorkflowsAndroidInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: AndroidInstallation,
    modifySteps: workflowsModifySteps,
})
const WorkflowsIOSInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: IOSInstallation,
    modifySteps: workflowsModifySteps,
})
const WorkflowsFlutterInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: FlutterInstallation,
    modifySteps: workflowsModifySteps,
})
const WorkflowsRNInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: ReactNativeInstallation,
    modifySteps: workflowsModifySteps,
})

// Server-side SDKs
const WorkflowsNodeInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: NodeJSInstallation,
    modifySteps: workflowsModifySteps,
})
const WorkflowsPythonInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: PythonInstallation,
    modifySteps: workflowsModifySteps,
})
const WorkflowsDjangoInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: DjangoInstallation,
    modifySteps: workflowsModifySteps,
})
const WorkflowsGoInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: GoInstallation,
    modifySteps: workflowsModifySteps,
})
const WorkflowsPHPInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: PHPInstallation,
    modifySteps: workflowsModifySteps,
})
const WorkflowsLaravelInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: LaravelInstallation,
    modifySteps: workflowsModifySteps,
})
const WorkflowsRubyInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: RubyInstallation,
    modifySteps: workflowsModifySteps,
})
const WorkflowsElixirInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: ElixirInstallation,
    modifySteps: workflowsModifySteps,
})

// API
const WorkflowsAPIInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: APIInstallation,
    modifySteps: workflowsModifySteps,
})

// Integrations
const WorkflowsSegmentInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: SegmentInstallation,
    modifySteps: workflowsModifySteps,
})
const WorkflowsRudderstackInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: RudderstackInstallation,
    modifySteps: workflowsModifySteps,
})
const WorkflowsSentryInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: SentryInstallation,
    modifySteps: workflowsModifySteps,
})
const WorkflowsZapierInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: ZapierInstallation,
    modifySteps: workflowsModifySteps,
})
const WorkflowsN8nInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: N8nInstallation,
    modifySteps: workflowsModifySteps,
})
const WorkflowsMoEngageInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: MoEngageInstallation,
    modifySteps: workflowsModifySteps,
})

// LLM Integrations
const WorkflowsHeliconeInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: HeliconeInstallation,
    modifySteps: workflowsModifySteps,
})
const WorkflowsLangfuseInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: LangfuseInstallation,
    modifySteps: workflowsModifySteps,
})
const WorkflowsTraceloopInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: TraceloopInstallation,
    modifySteps: workflowsModifySteps,
})

export const WorkflowsSDKTagOverrides: SDKTagOverrides = {
    [SDKKey.HELICONE]: [SDKTag.LLM],
}

export const WorkflowsSDKInstructions: SDKInstructionsMap = {
    [SDKKey.JS_WEB]: WorkflowsJSWebInstructionsWrapper,
    [SDKKey.ANDROID]: WorkflowsAndroidInstructionsWrapper,
    [SDKKey.ANGULAR]: WorkflowsAngularInstructionsWrapper,
    [SDKKey.API]: WorkflowsAPIInstructionsWrapper,
    [SDKKey.ASTRO]: WorkflowsAstroInstructionsWrapper,
    [SDKKey.BUBBLE]: WorkflowsBubbleInstructionsWrapper,
    [SDKKey.DJANGO]: WorkflowsDjangoInstructionsWrapper,
    [SDKKey.DOCUSAURUS]: WorkflowsDocusaurusInstructionsWrapper,
    [SDKKey.ELIXIR]: WorkflowsElixirInstructionsWrapper,
    [SDKKey.FLUTTER]: WorkflowsFlutterInstructionsWrapper,
    [SDKKey.FRAMER]: WorkflowsFramerInstructionsWrapper,
    [SDKKey.GO]: WorkflowsGoInstructionsWrapper,
    [SDKKey.GOOGLE_TAG_MANAGER]: WorkflowsGoogleTagManagerInstructionsWrapper,
    [SDKKey.HELICONE]: WorkflowsHeliconeInstructionsWrapper,
    [SDKKey.HTML_SNIPPET]: WorkflowsHTMLSnippetInstructionsWrapper,
    [SDKKey.IOS]: WorkflowsIOSInstructionsWrapper,
    [SDKKey.LANGFUSE]: WorkflowsLangfuseInstructionsWrapper,
    [SDKKey.LARAVEL]: WorkflowsLaravelInstructionsWrapper,
    [SDKKey.MOENGAGE]: WorkflowsMoEngageInstructionsWrapper,
    [SDKKey.N8N]: WorkflowsN8nInstructionsWrapper,
    [SDKKey.NEXT_JS]: WorkflowsNextJSInstructionsWrapper,
    [SDKKey.NODE_JS]: WorkflowsNodeInstructionsWrapper,
    [SDKKey.NUXT_JS]: WorkflowsNuxtJSInstructionsWrapper,
    [SDKKey.PHP]: WorkflowsPHPInstructionsWrapper,
    [SDKKey.PYTHON]: WorkflowsPythonInstructionsWrapper,
    [SDKKey.REACT]: WorkflowsReactInstructionsWrapper,
    [SDKKey.REACT_NATIVE]: WorkflowsRNInstructionsWrapper,
    [SDKKey.REMIX]: WorkflowsRemixJSInstructionsWrapper,
    [SDKKey.RETOOL]: WorkflowsRetoolInstructionsWrapper,
    [SDKKey.RUBY]: WorkflowsRubyInstructionsWrapper,
    [SDKKey.RUDDERSTACK]: WorkflowsRudderstackInstructionsWrapper,
    [SDKKey.SEGMENT]: WorkflowsSegmentInstructionsWrapper,
    [SDKKey.SENTRY]: WorkflowsSentryInstructionsWrapper,
    [SDKKey.SHOPIFY]: WorkflowsShopifyInstructionsWrapper,
    [SDKKey.SVELTE]: WorkflowsSvelteInstructionsWrapper,
    [SDKKey.TANSTACK_START]: WorkflowsTanStackInstructionsWrapper,
    [SDKKey.TRACELOOP]: WorkflowsTraceloopInstructionsWrapper,
    [SDKKey.VITE]: WorkflowsReactInstructionsWrapper,
    [SDKKey.VUE_JS]: WorkflowsVueInstructionsWrapper,
    [SDKKey.WEBFLOW]: WorkflowsWebflowInstructionsWrapper,
    [SDKKey.WORDPRESS]: WorkflowsWordpressInstructionsWrapper,
    [SDKKey.ZAPIER]: WorkflowsZapierInstructionsWrapper,
}
