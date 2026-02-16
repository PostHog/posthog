import { useValues } from 'kea'
import { useMemo, useState } from 'react'

import { LemonButton, LemonModal, LemonSelect, LemonSelectOptions, LemonSkeleton } from '@posthog/lemon-ui'
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
    IOSInstallation,
    JSEventCapture,
    JSWebInstallation,
    LaravelInstallation,
    NextJSInstallation,
    NodeEventCapture,
    NodeJSInstallation,
    NuxtInstallation,
    PHPInstallation,
    PythonEventCapture,
    PythonInstallation,
    ReactInstallation,
    ReactNativeInstallation,
    RemixInstallation,
    RubyInstallation,
    RubyOnRailsInstallation,
    SvelteInstallation,
    TanStackInstallation,
    VueInstallation,
    WebflowInstallation,
} from '@posthog/shared-onboarding/product-analytics'

import { JSSnippet } from 'lib/components/JSSnippet'
import { Link } from 'lib/lemon-ui/Link'
import { OnboardingDocsContentWrapper } from 'scenes/onboarding/OnboardingDocsContentWrapper'
import SetupWizardBanner from 'scenes/onboarding/sdks/sdk-install-instructions/components/SetupWizardBanner'
import { teamLogic } from 'scenes/teamLogic'

import { SDKKey } from '~/types'

import type { StepDefinition } from '../../../../../docs/onboarding/steps'

const JS_WEB_SNIPPETS = { JSEventCapture }
const NODE_SNIPPETS = { NodeEventCapture }
const PYTHON_SNIPPETS = { PythonEventCapture }

const filterToFirstRequiredStep = (steps: StepDefinition[]): StepDefinition[] => {
    const first = steps.find((s) => s.badge === 'required')
    return first ? [first] : steps.slice(0, 1)
}

const filterRequiredSteps = (steps: StepDefinition[]): StepDefinition[] => steps.filter((s) => s.badge === 'required')

interface SDKConfig {
    Installation: React.ComponentType<{ modifySteps?: (steps: StepDefinition[]) => StepDefinition[] }>
    snippets?: Record<string, React.ComponentType>
    wizardIntegrationName?: string
    docsLink: string
    name: string
}

const SDK_CONFIGS: Record<string, SDKConfig> = {
    // Popular
    [SDKKey.HTML_SNIPPET]: {
        Installation: HTMLSnippetInstallation,
        snippets: JS_WEB_SNIPPETS,
        name: 'HTML snippet',
        docsLink: 'https://posthog.com/docs/libraries/js',
    },
    [SDKKey.JS_WEB]: {
        Installation: JSWebInstallation,
        snippets: JS_WEB_SNIPPETS,
        name: 'JavaScript web',
        docsLink: 'https://posthog.com/docs/libraries/js',
    },
    [SDKKey.REACT]: {
        Installation: ReactInstallation,
        snippets: JS_WEB_SNIPPETS,
        wizardIntegrationName: 'React',
        name: 'React',
        docsLink: 'https://posthog.com/docs/libraries/react',
    },
    [SDKKey.NEXT_JS]: {
        Installation: NextJSInstallation,
        snippets: JS_WEB_SNIPPETS,
        wizardIntegrationName: 'Next.js',
        name: 'Next.js',
        docsLink: 'https://posthog.com/docs/libraries/next-js',
    },
    [SDKKey.NODE_JS]: {
        Installation: NodeJSInstallation,
        snippets: NODE_SNIPPETS,
        name: 'Node.js',
        docsLink: 'https://posthog.com/docs/libraries/node',
    },
    [SDKKey.PYTHON]: {
        Installation: PythonInstallation,
        snippets: PYTHON_SNIPPETS,
        name: 'Python',
        docsLink: 'https://posthog.com/docs/libraries/python',
    },
    [SDKKey.REACT_NATIVE]: {
        Installation: ReactNativeInstallation,
        wizardIntegrationName: 'React Native',
        name: 'React Native',
        docsLink: 'https://posthog.com/docs/libraries/react-native',
    },

    // Web
    [SDKKey.ANGULAR]: {
        Installation: AngularInstallation,
        snippets: JS_WEB_SNIPPETS,
        name: 'Angular',
        docsLink: 'https://posthog.com/docs/libraries/angular',
    },
    [SDKKey.ASTRO]: {
        Installation: AstroInstallation,
        snippets: JS_WEB_SNIPPETS,
        wizardIntegrationName: 'Astro',
        name: 'Astro',
        docsLink: 'https://posthog.com/docs/libraries/astro',
    },
    [SDKKey.BUBBLE]: {
        Installation: BubbleInstallation,
        snippets: JS_WEB_SNIPPETS,
        name: 'Bubble',
        docsLink: 'https://posthog.com/docs/libraries/bubble',
    },
    [SDKKey.FRAMER]: {
        Installation: FramerInstallation,
        snippets: JS_WEB_SNIPPETS,
        name: 'Framer',
        docsLink: 'https://posthog.com/docs/libraries/framer',
    },
    [SDKKey.NUXT_JS]: {
        Installation: NuxtInstallation,
        snippets: JS_WEB_SNIPPETS,
        name: 'Nuxt.js',
        docsLink: 'https://posthog.com/docs/libraries/nuxt-js',
    },
    [SDKKey.REMIX]: {
        Installation: RemixInstallation,
        snippets: JS_WEB_SNIPPETS,
        name: 'Remix',
        docsLink: 'https://posthog.com/docs/libraries/remix',
    },
    [SDKKey.SVELTE]: {
        Installation: SvelteInstallation,
        snippets: JS_WEB_SNIPPETS,
        wizardIntegrationName: 'Svelte',
        name: 'Svelte',
        docsLink: 'https://posthog.com/docs/libraries/svelte',
    },
    [SDKKey.TANSTACK_START]: {
        Installation: TanStackInstallation,
        snippets: JS_WEB_SNIPPETS,
        name: 'TanStack Start',
        docsLink: 'https://posthog.com/docs/libraries/react',
    },
    [SDKKey.VUE_JS]: {
        Installation: VueInstallation,
        snippets: JS_WEB_SNIPPETS,
        name: 'Vue.js',
        docsLink: 'https://posthog.com/docs/libraries/vue-js',
    },
    [SDKKey.WEBFLOW]: {
        Installation: WebflowInstallation,
        snippets: JS_WEB_SNIPPETS,
        name: 'Webflow',
        docsLink: 'https://posthog.com/docs/libraries/webflow',
    },

    // Mobile
    [SDKKey.ANDROID]: {
        Installation: AndroidInstallation,
        name: 'Android',
        docsLink: 'https://posthog.com/docs/libraries/android',
    },
    [SDKKey.FLUTTER]: {
        Installation: FlutterInstallation,
        name: 'Flutter',
        docsLink: 'https://posthog.com/docs/libraries/flutter',
    },
    [SDKKey.IOS]: {
        Installation: IOSInstallation,
        name: 'iOS',
        docsLink: 'https://posthog.com/docs/libraries/ios',
    },

    // Server
    [SDKKey.DJANGO]: {
        Installation: DjangoInstallation,
        snippets: PYTHON_SNIPPETS,
        wizardIntegrationName: 'Django',
        name: 'Django',
        docsLink: 'https://posthog.com/docs/libraries/django',
    },
    [SDKKey.ELIXIR]: {
        Installation: ElixirInstallation,
        name: 'Elixir',
        docsLink: 'https://posthog.com/docs/libraries/elixir',
    },
    [SDKKey.GO]: {
        Installation: GoInstallation,
        name: 'Go',
        docsLink: 'https://posthog.com/docs/libraries/go',
    },
    [SDKKey.LARAVEL]: {
        Installation: LaravelInstallation,
        name: 'Laravel',
        docsLink: 'https://posthog.com/docs/libraries/laravel',
    },
    [SDKKey.PHP]: {
        Installation: PHPInstallation,
        name: 'PHP',
        docsLink: 'https://posthog.com/docs/libraries/php',
    },
    [SDKKey.RUBY]: {
        Installation: RubyInstallation,
        name: 'Ruby',
        docsLink: 'https://posthog.com/docs/libraries/ruby',
    },
    [SDKKey.RUBY_ON_RAILS]: {
        Installation: RubyOnRailsInstallation,
        name: 'Ruby on Rails',
        docsLink: 'https://posthog.com/docs/libraries/rails',
    },

    // Integrations
    [SDKKey.API]: {
        Installation: APIInstallation,
        name: 'API',
        docsLink: 'https://posthog.com/docs/api',
    },
    [SDKKey.DOCUSAURUS]: {
        Installation: DocusaurusInstallation,
        name: 'Docusaurus',
        docsLink: 'https://posthog.com/docs/libraries/docusaurus',
    },
    [SDKKey.GOOGLE_TAG_MANAGER]: {
        Installation: GoogleTagManagerInstallation,
        snippets: JS_WEB_SNIPPETS,
        name: 'Google Tag Manager',
        docsLink: 'https://posthog.com/docs/libraries/google-tag-manager',
    },
}

const SDK_SELECT_OPTIONS: LemonSelectOptions<string> = [
    {
        title: 'Popular',
        options: [
            { value: SDKKey.HTML_SNIPPET, label: 'HTML snippet' },
            { value: SDKKey.JS_WEB, label: 'JavaScript web' },
            { value: SDKKey.REACT, label: 'React' },
            { value: SDKKey.NEXT_JS, label: 'Next.js' },
            { value: SDKKey.PYTHON, label: 'Python' },
            { value: SDKKey.NODE_JS, label: 'Node.js' },
            { value: SDKKey.REACT_NATIVE, label: 'React Native' },
        ],
    },
    {
        title: 'Web',
        options: [
            { value: SDKKey.ANGULAR, label: 'Angular' },
            { value: SDKKey.ASTRO, label: 'Astro' },
            { value: SDKKey.BUBBLE, label: 'Bubble' },
            { value: SDKKey.FRAMER, label: 'Framer' },
            { value: SDKKey.NUXT_JS, label: 'Nuxt.js' },
            { value: SDKKey.REMIX, label: 'Remix' },
            { value: SDKKey.SVELTE, label: 'Svelte' },
            { value: SDKKey.TANSTACK_START, label: 'TanStack Start' },
            { value: SDKKey.VUE_JS, label: 'Vue.js' },
            { value: SDKKey.WEBFLOW, label: 'Webflow' },
        ],
    },
    {
        title: 'Mobile',
        options: [
            { value: SDKKey.ANDROID, label: 'Android' },
            { value: SDKKey.FLUTTER, label: 'Flutter' },
            { value: SDKKey.IOS, label: 'iOS' },
        ],
    },
    {
        title: 'Server',
        options: [
            { value: SDKKey.DJANGO, label: 'Django' },
            { value: SDKKey.ELIXIR, label: 'Elixir' },
            { value: SDKKey.GO, label: 'Go' },
            { value: SDKKey.LARAVEL, label: 'Laravel' },
            { value: SDKKey.PHP, label: 'PHP' },
            { value: SDKKey.RUBY, label: 'Ruby' },
            { value: SDKKey.RUBY_ON_RAILS, label: 'Ruby on Rails' },
        ],
    },
    {
        title: 'Integrations',
        options: [
            { value: SDKKey.API, label: 'API' },
            { value: SDKKey.DOCUSAURUS, label: 'Docusaurus' },
            { value: SDKKey.GOOGLE_TAG_MANAGER, label: 'Google Tag Manager' },
        ],
    },
]

export function SDKSetupInstructions(): JSX.Element {
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const [selectedSDK, setSelectedSDK] = useState<string>(SDKKey.HTML_SNIPPET)
    const [showFullSetup, setShowFullSetup] = useState(false)

    const config = useMemo(() => SDK_CONFIGS[selectedSDK], [selectedSDK])

    if (currentTeamLoading && !currentTeam) {
        return (
            <div className="space-y-4">
                <LemonSkeleton className="w-1/2 h-4" />
                <LemonSkeleton repeat={3} />
            </div>
        )
    }

    if (!config) {
        return <></>
    }

    const { Installation, snippets, wizardIntegrationName, docsLink, name } = config
    const isHTMLSnippet = selectedSDK === SDKKey.HTML_SNIPPET

    return (
        <div className="space-y-4 max-w-200">
            <LemonSelect
                value={selectedSDK}
                onChange={(value) => {
                    setSelectedSDK(value)
                    setShowFullSetup(false)
                }}
                options={SDK_SELECT_OPTIONS}
                className="max-w-80"
            />
            {isHTMLSnippet ? (
                <JSSnippet />
            ) : (
                <OnboardingDocsContentWrapper snippets={snippets} minimal>
                    <Installation modifySteps={filterToFirstRequiredStep} />
                </OnboardingDocsContentWrapper>
            )}
            <div className="flex items-center gap-2">
                <LemonButton type="secondary" size="small" onClick={() => setShowFullSetup(true)}>
                    View full setup instructions
                </LemonButton>
                <Link to={docsLink} target="_blank" className="text-sm">
                    {name} docs
                </Link>
            </div>
            <LemonModal
                isOpen={showFullSetup}
                onClose={() => setShowFullSetup(false)}
                title={`${name} setup`}
                width={640}
            >
                {wizardIntegrationName && <SetupWizardBanner integrationName={wizardIntegrationName} />}
                <OnboardingDocsContentWrapper snippets={snippets}>
                    <Installation modifySteps={filterRequiredSteps} />
                </OnboardingDocsContentWrapper>
                <div className="mt-4">
                    <Link to={docsLink} target="_blank">
                        View full {name} documentation
                    </Link>
                </div>
            </LemonModal>
        </div>
    )
}
