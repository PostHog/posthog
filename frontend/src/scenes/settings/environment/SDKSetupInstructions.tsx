import { useValues } from 'kea'
import { useMemo, useState } from 'react'

import { LemonButton, LemonModal, LemonSelect, LemonSelectSection, LemonSkeleton } from '@posthog/lemon-ui'
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
    IOSInstallation,
    JSEventCapture,
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
    WebInstallation,
    WebflowInstallation,
} from '@posthog/shared-onboarding/product-analytics'
import type { StepDefinition } from '@posthog/shared-onboarding/steps'

import { Link } from 'lib/lemon-ui/Link'
import { OnboardingDocsContentWrapper } from 'scenes/onboarding/OnboardingDocsContentWrapper'
import SetupWizardBanner from 'scenes/onboarding/sdks/sdk-install-instructions/components/SetupWizardBanner'
import { teamLogic } from 'scenes/teamLogic'

import { SDKKey } from '~/types'

const JS_WEB_SNIPPETS = { JSEventCapture }
const NODE_SNIPPETS = { NodeEventCapture }
const PYTHON_SNIPPETS = { PythonEventCapture }

export const filterToFirstRequiredStep = (steps: StepDefinition[]): StepDefinition[] => {
    const first = steps.find((s) => s.badge === 'required')
    return first ? [first] : steps.slice(0, 1)
}

export const filterRequiredSteps = (steps: StepDefinition[]): StepDefinition[] =>
    steps.filter((s) => s.badge === 'required')

export type SDKCategory = 'web' | 'mobile' | 'server' | 'integration'

interface SDKConfig {
    Installation: React.ComponentType<{ modifySteps?: (steps: StepDefinition[]) => StepDefinition[] }>
    snippets?: Record<string, React.ComponentType>
    wizardIntegrationName?: string
    docsLink: string
    name: string
    category: SDKCategory
    popular?: boolean
}

export const SDK_CONFIGS: { [key in SDKKey]?: SDKConfig } = {
    // Popular
    [SDKKey.JS_WEB]: {
        Installation: WebInstallation,
        snippets: JS_WEB_SNIPPETS,
        name: 'Web',
        docsLink: 'https://posthog.com/docs/libraries/js',
        category: 'web',
        popular: true,
    },
    [SDKKey.REACT]: {
        Installation: ReactInstallation,
        snippets: JS_WEB_SNIPPETS,
        wizardIntegrationName: 'React',
        name: 'React',
        docsLink: 'https://posthog.com/docs/libraries/react',
        category: 'web',
        popular: true,
    },
    [SDKKey.NEXT_JS]: {
        Installation: NextJSInstallation,
        snippets: JS_WEB_SNIPPETS,
        wizardIntegrationName: 'Next.js',
        name: 'Next.js',
        docsLink: 'https://posthog.com/docs/libraries/next-js',
        category: 'web',
        popular: true,
    },
    [SDKKey.NODE_JS]: {
        Installation: NodeJSInstallation,
        snippets: NODE_SNIPPETS,
        name: 'Node.js',
        docsLink: 'https://posthog.com/docs/libraries/node',
        category: 'server',
        popular: true,
    },
    [SDKKey.PYTHON]: {
        Installation: PythonInstallation,
        snippets: PYTHON_SNIPPETS,
        name: 'Python',
        docsLink: 'https://posthog.com/docs/libraries/python',
        category: 'server',
        popular: true,
    },
    [SDKKey.REACT_NATIVE]: {
        Installation: ReactNativeInstallation,
        wizardIntegrationName: 'React Native',
        name: 'React Native',
        docsLink: 'https://posthog.com/docs/libraries/react-native',
        category: 'mobile',
        popular: true,
    },

    // Web
    [SDKKey.ANGULAR]: {
        Installation: AngularInstallation,
        snippets: JS_WEB_SNIPPETS,
        name: 'Angular',
        docsLink: 'https://posthog.com/docs/libraries/angular',
        category: 'web',
    },
    [SDKKey.ASTRO]: {
        Installation: AstroInstallation,
        snippets: JS_WEB_SNIPPETS,
        wizardIntegrationName: 'Astro',
        name: 'Astro',
        docsLink: 'https://posthog.com/docs/libraries/astro',
        category: 'web',
    },
    [SDKKey.BUBBLE]: {
        Installation: BubbleInstallation,
        snippets: JS_WEB_SNIPPETS,
        name: 'Bubble',
        docsLink: 'https://posthog.com/docs/libraries/bubble',
        category: 'web',
    },
    [SDKKey.FRAMER]: {
        Installation: FramerInstallation,
        snippets: JS_WEB_SNIPPETS,
        name: 'Framer',
        docsLink: 'https://posthog.com/docs/libraries/framer',
        category: 'web',
    },
    [SDKKey.NUXT_JS]: {
        Installation: NuxtInstallation,
        snippets: JS_WEB_SNIPPETS,
        name: 'Nuxt.js',
        docsLink: 'https://posthog.com/docs/libraries/nuxt-js',
        category: 'web',
    },
    [SDKKey.REMIX]: {
        Installation: RemixInstallation,
        snippets: JS_WEB_SNIPPETS,
        name: 'Remix',
        docsLink: 'https://posthog.com/docs/libraries/remix',
        category: 'web',
    },
    [SDKKey.SVELTE]: {
        Installation: SvelteInstallation,
        snippets: JS_WEB_SNIPPETS,
        wizardIntegrationName: 'Svelte',
        name: 'Svelte',
        docsLink: 'https://posthog.com/docs/libraries/svelte',
        category: 'web',
    },
    [SDKKey.TANSTACK_START]: {
        Installation: TanStackInstallation,
        snippets: JS_WEB_SNIPPETS,
        name: 'TanStack Start',
        docsLink: 'https://posthog.com/docs/libraries/react',
        category: 'web',
    },
    [SDKKey.VUE_JS]: {
        Installation: VueInstallation,
        snippets: JS_WEB_SNIPPETS,
        name: 'Vue.js',
        docsLink: 'https://posthog.com/docs/libraries/vue-js',
        category: 'web',
    },
    [SDKKey.WEBFLOW]: {
        Installation: WebflowInstallation,
        snippets: JS_WEB_SNIPPETS,
        name: 'Webflow',
        docsLink: 'https://posthog.com/docs/libraries/webflow',
        category: 'web',
    },

    // Mobile
    [SDKKey.ANDROID]: {
        Installation: AndroidInstallation,
        name: 'Android',
        docsLink: 'https://posthog.com/docs/libraries/android',
        category: 'mobile',
    },
    [SDKKey.FLUTTER]: {
        Installation: FlutterInstallation,
        name: 'Flutter',
        docsLink: 'https://posthog.com/docs/libraries/flutter',
        category: 'mobile',
    },
    [SDKKey.IOS]: {
        Installation: IOSInstallation,
        name: 'iOS',
        docsLink: 'https://posthog.com/docs/libraries/ios',
        category: 'mobile',
    },

    // Server
    [SDKKey.DJANGO]: {
        Installation: DjangoInstallation,
        snippets: PYTHON_SNIPPETS,
        wizardIntegrationName: 'Django',
        name: 'Django',
        docsLink: 'https://posthog.com/docs/libraries/django',
        category: 'server',
    },
    [SDKKey.ELIXIR]: {
        Installation: ElixirInstallation,
        name: 'Elixir',
        docsLink: 'https://posthog.com/docs/libraries/elixir',
        category: 'server',
    },
    [SDKKey.GO]: {
        Installation: GoInstallation,
        name: 'Go',
        docsLink: 'https://posthog.com/docs/libraries/go',
        category: 'server',
    },
    [SDKKey.LARAVEL]: {
        Installation: LaravelInstallation,
        name: 'Laravel',
        docsLink: 'https://posthog.com/docs/libraries/laravel',
        category: 'server',
    },
    [SDKKey.PHP]: {
        Installation: PHPInstallation,
        name: 'PHP',
        docsLink: 'https://posthog.com/docs/libraries/php',
        category: 'server',
    },
    [SDKKey.RUBY]: {
        Installation: RubyInstallation,
        name: 'Ruby',
        docsLink: 'https://posthog.com/docs/libraries/ruby',
        category: 'server',
    },
    [SDKKey.RUBY_ON_RAILS]: {
        Installation: RubyOnRailsInstallation,
        name: 'Ruby on Rails',
        docsLink: 'https://posthog.com/docs/libraries/rails',
        category: 'server',
    },

    // Integrations
    [SDKKey.API]: {
        Installation: APIInstallation,
        name: 'API',
        docsLink: 'https://posthog.com/docs/api',
        category: 'integration',
    },
    [SDKKey.DOCUSAURUS]: {
        Installation: DocusaurusInstallation,
        name: 'Docusaurus',
        docsLink: 'https://posthog.com/docs/libraries/docusaurus',
        category: 'integration',
    },
    [SDKKey.GOOGLE_TAG_MANAGER]: {
        Installation: GoogleTagManagerInstallation,
        snippets: JS_WEB_SNIPPETS,
        name: 'Google Tag Manager',
        docsLink: 'https://posthog.com/docs/libraries/google-tag-manager',
        category: 'integration',
    },
}

const CATEGORY_TITLES: Record<SDKCategory, string> = {
    web: 'Web',
    mobile: 'Mobile',
    server: 'Server',
    integration: 'Integrations',
}

export function buildSDKSelectOptions(categories?: SDKCategory[]): LemonSelectSection<SDKKey>[] {
    const entries = Object.entries(SDK_CONFIGS) as [SDKKey, SDKConfig][]
    const filtered = categories ? entries.filter(([_, c]) => categories.includes(c.category)) : entries

    const groups: LemonSelectSection<SDKKey>[] = []

    const popular = filtered.filter(([_, c]) => c.popular)
    if (popular.length > 0) {
        groups.push({ title: 'Popular', options: popular.map(([k, c]) => ({ value: k, label: c.name })) })
    }

    for (const cat of ['web', 'mobile', 'server', 'integration'] as const) {
        if (categories && !categories.includes(cat)) {
            continue
        }
        const items = filtered.filter(([_, c]) => c.category === cat && !c.popular)
        if (items.length > 0) {
            groups.push({ title: CATEGORY_TITLES[cat], options: items.map(([k, c]) => ({ value: k, label: c.name })) })
        }
    }

    return groups
}

export function SDKSetupInstructions(): JSX.Element {
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const [selectedSDK, setSelectedSDK] = useState<SDKKey>(SDKKey.JS_WEB)
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

    const { Installation, snippets, wizardIntegrationName, docsLink, name, category } = config
    const isClientSideSDK = category === 'web' || category === 'mobile'

    return (
        <div className="space-y-4 max-w-200">
            <LemonSelect
                value={selectedSDK}
                onChange={(value) => {
                    setSelectedSDK(value)
                    setShowFullSetup(false)
                }}
                options={buildSDKSelectOptions()}
                className="max-w-80"
            />
            <OnboardingDocsContentWrapper snippets={snippets} minimal useReverseProxy={isClientSideSDK}>
                <Installation modifySteps={filterToFirstRequiredStep} />
            </OnboardingDocsContentWrapper>
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
                <OnboardingDocsContentWrapper snippets={snippets} useReverseProxy={isClientSideSDK}>
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
