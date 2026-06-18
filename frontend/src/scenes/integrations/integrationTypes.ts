import { IntegrationKind } from '~/types'

/** The actionable connect section, reused in both settings and the full page. */
export type SettingsSectionComponent = (props: { next?: string }) => JSX.Element

/**
 * Pure metadata describing an integration. Deliberately holds no components so each
 * integration is easy to reason about — components are bundled onto {@link Integration}.
 */
export interface IntegrationDefinition {
    /** URL slug, e.g. 'slack'. Also the registry key. */
    slug: string
    /** Underlying integration kind used to detect whether it is already connected. */
    kind: IntegrationKind
    /** Display name, e.g. 'Slack'. */
    name: string
    /** Logo image src. */
    logo: string
    /** Optional wide banner image src, shown at the top of the landing page. */
    banner?: string
    /** One-line subtitle shown under the title. */
    subtitle: string
    /** Longer explanation of what PostHog does with this integration. */
    description: string | JSX.Element
    /** Bullets shown on the success screen — what the user can do once connected. */
    capabilities: string[]
    /** Optional documentation link. */
    docsUrl?: string
}

/** A definition bundled with its renderable components. */
export interface Integration extends IntegrationDefinition {
    /** The connect/manage section embedded in settings. */
    SettingsSection: SettingsSectionComponent
    /** The standalone, chrome-less landing page. */
    FullPage: () => JSX.Element
}
