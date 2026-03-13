import { useValues } from 'kea'
import posthog from 'posthog-js'

import { buildJsHtmlSnippet, SnippetOption } from '@posthog/shared-onboarding/product-analytics'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { domainFor, proxyLogic } from 'scenes/settings/environment/proxyLogic'
import { teamLogic } from 'scenes/teamLogic'

import { SDK_DEFAULTS_DATE } from '~/loadPostHogJS'

function getPosthogMethods(): string[] {
    const methods: string[] = []
    const posthogPrototype = Object.getPrototypeOf(posthog)
    for (const key of Object.getOwnPropertyNames(posthogPrototype)) {
        if (
            typeof posthogPrototype[key] === 'function' &&
            !key.startsWith('_') &&
            !['constructor', 'toString', 'push'].includes(key)
        ) {
            methods.push(key)
        }
    }
    return methods
}

export interface JsSnippetConfig {
    projectToken: string
    methods: string[]
    options: Record<string, SnippetOption>
}

export function useJsSnippetConfig(): JsSnippetConfig {
    const { currentTeam } = useValues(teamLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { preflight } = useValues(preflightLogic)

    const { proxyRecords } = useValues(proxyLogic)
    const proxyRecord = proxyRecords[0]

    const isPersonProfilesDisabled = featureFlags[FEATURE_FLAGS.PERSONLESS_EVENTS_NOT_SUPPORTED]

    return {
        projectToken: currentTeam?.api_token ?? '',
        methods: getPosthogMethods(),
        options: {
            api_host: {
                content: domainFor(proxyRecord),
                comment: proxyRecord ? 'your managed reverse proxy domain' : undefined,
                enabled: true,
            },
            ui_host: {
                content: preflight?.site_url || window.location.origin,
                comment: "necessary because you're using a proxy, this way links will point back to PostHog properly",
                enabled: !!proxyRecord,
            },
            defaults: {
                content: SDK_DEFAULTS_DATE,
                enabled: true,
            },
            person_profiles: {
                content: 'identified_only',
                comment: "or 'always' to create profiles for anonymous users as well",
                enabled: !isPersonProfilesDisabled,
            },
        },
    }
}

export function useJsSnippet(indent = 0, arrayJs?: string, scriptAttributes?: string): string {
    const { projectToken, methods, options } = useJsSnippetConfig()

    return buildJsHtmlSnippet({
        projectToken,
        methods,
        options,
        indent,
        arrayJs,
        scriptAttributes,
    })
}

export function JSSnippet(): JSX.Element {
    const snippet = useJsSnippet()

    return <CodeSnippet language={Language.HTML}>{snippet}</CodeSnippet>
}

export function JSSnippetV2(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)

    const snippet = useJsSnippet(0, `/array/${currentTeam?.api_token}/array.js`)

    return <CodeSnippet language={Language.HTML}>{snippet}</CodeSnippet>
}
