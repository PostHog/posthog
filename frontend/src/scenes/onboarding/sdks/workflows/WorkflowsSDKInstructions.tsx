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
    HeliconeInstallation,
    IOSInstallation,
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
    ReactRouterInstallation,
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
    WebInstallation,
    ZapierInstallation,
    NodeEventCapture,
    PythonEventCapture,
} from '@posthog/shared-onboarding/product-analytics'
import { StepDefinition } from '@posthog/shared-onboarding/steps'

import { useMDXComponents } from 'scenes/onboarding/OnboardingDocsContentWrapper'
import { JS_WEB_SNIPPETS } from 'scenes/onboarding/sdks/shared/jsWebSnippets'

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

const NODE_SNIPPETS = { NodeEventCapture }
const PYTHON_SNIPPETS = { PythonEventCapture }

// JS Web SDKs
const WorkflowsWebInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: WebInstallation,
    modifySteps: workflowsModifySteps,
    snippets: JS_WEB_SNIPPETS,
})

// Frontend frameworks
const WorkflowsReactInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: ReactInstallation,
    modifySteps: workflowsModifySteps,
    wizardIntegrationName: 'React',
    snippets: JS_WEB_SNIPPETS,
})
const WorkflowsNextJSInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: NextJSInstallation,
    modifySteps: workflowsModifySteps,
    wizardIntegrationName: 'Next.js',
    snippets: JS_WEB_SNIPPETS,
})
const WorkflowsSvelteInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: SvelteInstallation,
    modifySteps: workflowsModifySteps,
    wizardIntegrationName: 'Svelte',
    snippets: JS_WEB_SNIPPETS,
})
const WorkflowsAstroInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: AstroInstallation,
    modifySteps: workflowsModifySteps,
    wizardIntegrationName: 'Astro',
    snippets: JS_WEB_SNIPPETS,
})
const WorkflowsTanStackInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: TanStackInstallation,
    modifySteps: workflowsModifySteps,
    wizardIntegrationName: 'TanStack Start',
    snippets: JS_WEB_SNIPPETS,
})
const WorkflowsAngularInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: AngularInstallation,
    modifySteps: workflowsModifySteps,
    wizardIntegrationName: 'Angular',
    snippets: JS_WEB_SNIPPETS,
})
const WorkflowsVueInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: VueInstallation,
    modifySteps: workflowsModifySteps,
    wizardIntegrationName: 'Vue',
    snippets: JS_WEB_SNIPPETS,
})
const WorkflowsNuxtJSInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: NuxtInstallation,
    modifySteps: workflowsModifySteps,
    wizardIntegrationName: 'Nuxt',
    snippets: JS_WEB_SNIPPETS,
})
const WorkflowsReactRouterInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: ReactRouterInstallation,
    modifySteps: workflowsModifySteps,
    snippets: JS_WEB_SNIPPETS,
})
const WorkflowsRemixJSInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: RemixInstallation,
    modifySteps: workflowsModifySteps,
    wizardIntegrationName: 'React Router',
    snippets: JS_WEB_SNIPPETS,
})

// Website builders
const WorkflowsBubbleInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: BubbleInstallation,
    modifySteps: workflowsModifySteps,
    snippets: JS_WEB_SNIPPETS,
})
const WorkflowsFramerInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: FramerInstallation,
    modifySteps: workflowsModifySteps,
    snippets: JS_WEB_SNIPPETS,
})
const WorkflowsWebflowInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: WebflowInstallation,
    modifySteps: workflowsModifySteps,
    snippets: JS_WEB_SNIPPETS,
})
const WorkflowsDocusaurusInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: DocusaurusInstallation,
    modifySteps: workflowsModifySteps,
    snippets: JS_WEB_SNIPPETS,
})
const WorkflowsGoogleTagManagerInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: GoogleTagManagerInstallation,
    modifySteps: workflowsModifySteps,
    snippets: JS_WEB_SNIPPETS,
})
const WorkflowsShopifyInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: ShopifyInstallation,
    modifySteps: workflowsModifySteps,
    snippets: JS_WEB_SNIPPETS,
})
const WorkflowsWordpressInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: WordpressInstallation,
    modifySteps: workflowsModifySteps,
    snippets: JS_WEB_SNIPPETS,
})
const WorkflowsRetoolInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: RetoolInstallation,
    modifySteps: workflowsModifySteps,
})

// Mobile SDKs
const WorkflowsAndroidInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: AndroidInstallation,
    modifySteps: workflowsModifySteps,
    wizardIntegrationName: 'Android',
})
const WorkflowsIOSInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: IOSInstallation,
    modifySteps: workflowsModifySteps,
    wizardIntegrationName: 'Swift',
})
const WorkflowsFlutterInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: FlutterInstallation,
    modifySteps: workflowsModifySteps,
})
const WorkflowsRNInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: ReactNativeInstallation,
    modifySteps: workflowsModifySteps,
    wizardIntegrationName: 'React Native',
})

// Server-side SDKs
const WorkflowsNodeInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: NodeJSInstallation,
    modifySteps: workflowsModifySteps,
    snippets: NODE_SNIPPETS,
})
const WorkflowsPythonInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: PythonInstallation,
    modifySteps: workflowsModifySteps,
    wizardIntegrationName: 'Python',
    snippets: PYTHON_SNIPPETS,
})
const WorkflowsDjangoInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: DjangoInstallation,
    modifySteps: workflowsModifySteps,
    wizardIntegrationName: 'Django',
    snippets: PYTHON_SNIPPETS,
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
    wizardIntegrationName: 'Laravel',
})
const WorkflowsRubyInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: RubyInstallation,
    modifySteps: workflowsModifySteps,
    wizardIntegrationName: 'Ruby',
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
    [SDKKey.JS_WEB]: WorkflowsWebInstructionsWrapper,
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
    [SDKKey.REACT_ROUTER]: WorkflowsReactRouterInstructionsWrapper,
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
