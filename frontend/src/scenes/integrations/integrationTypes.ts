import { IntegrationKind, IntegrationType } from '~/types'

/** The actionable connect section, reused in both settings and the full page. */
export type SettingsSectionComponent = (props: { next?: string }) => JSX.Element

/**
 * Optional slot rendered on the OAuth landing page directly below the success card,
 * for each connected integration of this kind. Use it to surface follow-up state
 * the user must act on while they're still in the install flow — missing scopes,
 * incomplete configuration, channel selection, etc. — rather than relegating it to
 * the integrations management screen they may never revisit.
 */
export type PostConnectComponent = (props: { integration: IntegrationType }) => JSX.Element

/** Aggregate state used by the OAuth landing page to pick its headline + icon. */
export type IntegrationStatus = 'ok' | 'needs_attention'

/**
 * Optional hook called once with every connected integration of this kind so the
 * landing page can switch from "Everything is set up" to a warning state when any
 * install needs follow-up action (e.g. missing scopes).
 *
 * Must follow the Rules of Hooks — call inner hooks unconditionally — because the
 * page invokes it exactly once on every render.
 */
export type IntegrationStatusHook = (integrations: IntegrationType[]) => IntegrationStatus

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
    /**
     * Optional component rendered per connected integration on the OAuth landing page,
     * below the success card. See {@link PostConnectComponent}.
     */
    PostConnect?: PostConnectComponent
    /**
     * Optional aggregate-status hook. When provided and it returns ``needs_attention``,
     * the landing page swaps the green checkmark + "Everything is set up and ready to go"
     * copy for a warning icon and follow-up copy that points at {@link PostConnect}.
     */
    useStatus?: IntegrationStatusHook
}

/** A definition bundled with its renderable components. */
export interface Integration extends IntegrationDefinition {
    /** The connect/manage section embedded in settings. */
    SettingsSection: SettingsSectionComponent
    /** The standalone, chrome-less landing page. */
    FullPage: () => JSX.Element
}
