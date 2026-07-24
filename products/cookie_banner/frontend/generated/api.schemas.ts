/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
/**
 * * `none` - none
 * * `posthog-logo` - posthog-logo
 * * `posthog-logomark-light` - posthog-logomark-light
 * * `hedgehog-builder` - hedgehog-builder
 * * `hedgehog-business` - hedgehog-business
 * * `hedgehog-hogzilla` - hedgehog-hogzilla
 * * `hedgehog-robot` - hedgehog-robot
 * * `hedgehog-mobile` - hedgehog-mobile
 * * `hedgehog-zen` - hedgehog-zen
 * * `hedgehog-lens` - hedgehog-lens
 * * `hedgehog-town-crier` - hedgehog-town-crier
 * * `hedgehog-wizard` - hedgehog-wizard
 * * `hedgehog-legal` - hedgehog-legal
 */
export type ArtStyleEnumApi = (typeof ArtStyleEnumApi)[keyof typeof ArtStyleEnumApi]

export const ArtStyleEnumApi = {
    None: 'none',
    PosthogLogo: 'posthog-logo',
    PosthogLogomarkLight: 'posthog-logomark-light',
    HedgehogBuilder: 'hedgehog-builder',
    HedgehogBusiness: 'hedgehog-business',
    HedgehogHogzilla: 'hedgehog-hogzilla',
    HedgehogRobot: 'hedgehog-robot',
    HedgehogMobile: 'hedgehog-mobile',
    HedgehogZen: 'hedgehog-zen',
    HedgehogLens: 'hedgehog-lens',
    HedgehogTownCrier: 'hedgehog-town-crier',
    HedgehogWizard: 'hedgehog-wizard',
    HedgehogLegal: 'hedgehog-legal',
} as const

/**
 * * `bottom-left` - bottom-left
 * * `bottom-right` - bottom-right
 * * `bottom-bar` - bottom-bar
 */
export type PositionEnumApi = (typeof PositionEnumApi)[keyof typeof PositionEnumApi]

export const PositionEnumApi = {
    BottomLeft: 'bottom-left',
    BottomRight: 'bottom-right',
    BottomBar: 'bottom-bar',
} as const

/**
 * Per-language overrides for the banner copy. Omitted keys fall back to the base
 * (untranslated) copy for visitors matching this language.
 */
export interface CookieBannerTranslationApi {
    /**
     * Translated banner headline.
     * @maxLength 25
     */
    title?: string
    /**
     * Translated body copy.
     * @maxLength 200
     */
    description?: string
    /**
     * Translated accept button label.
     * @maxLength 11
     */
    acceptButtonText?: string
    /**
     * Translated decline button label.
     * @maxLength 11
     */
    declineButtonText?: string
    /**
     * Translated 'Manage preferences' label.
     * @maxLength 25
     */
    preferencesButtonText?: string
}

/**
 * Per-language copy overrides keyed by ISO 639 language code (e.g. 'de', 'pt-BR'). The banner picks the visitor's browser language, falling back to the base copy.
 */
export type CookieBannerAppearanceApiTranslations = { [key: string]: CookieBannerTranslationApi }

/**
 * Appearance overrides for the banner. Omitted keys fall back to the PostHog-styled defaults
 * (see products/cookie_banner/backend/constants.py) when the banner is delivered.
 */
export interface CookieBannerAppearanceApi {
    /**
     * Banner headline. Plain text only. Defaults to 'We use cookies'.
     * @maxLength 25
     */
    title?: string
    /**
     * Body copy explaining what cookies are used for. Plain text only.
     * @maxLength 200
     */
    description?: string
    /**
     * Label for the button that opts the visitor in to tracking. Defaults to 'Accept'.
     * @maxLength 11
     */
    acceptButtonText?: string
    /**
     * Label for the button that opts the visitor out of tracking. Defaults to 'Decline'.
     * @maxLength 11
     */
    declineButtonText?: string
    /** Artwork shown on the banner: the PostHog logo, hedgehog art, or none. Defaults to 'posthog-logo'.
     *
     * * `none` - none
     * * `posthog-logo` - posthog-logo
     * * `posthog-logomark-light` - posthog-logomark-light
     * * `hedgehog-builder` - hedgehog-builder
     * * `hedgehog-business` - hedgehog-business
     * * `hedgehog-hogzilla` - hedgehog-hogzilla
     * * `hedgehog-robot` - hedgehog-robot
     * * `hedgehog-mobile` - hedgehog-mobile
     * * `hedgehog-zen` - hedgehog-zen
     * * `hedgehog-lens` - hedgehog-lens
     * * `hedgehog-town-crier` - hedgehog-town-crier
     * * `hedgehog-wizard` - hedgehog-wizard
     * * `hedgehog-legal` - hedgehog-legal */
    artStyle?: ArtStyleEnumApi
    /** Where the banner appears on the page. Defaults to 'bottom-right'.
     *
     * * `bottom-left` - bottom-left
     * * `bottom-right` - bottom-right
     * * `bottom-bar` - bottom-bar */
    position?: PositionEnumApi
    /**
     * Banner background color as a hex value. Defaults to '#eeefe9'.
     * @pattern ^#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$
     */
    backgroundColor?: string
    /**
     * Banner text color as a hex value. Defaults to '#151515'.
     * @pattern ^#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$
     */
    textColor?: string
    /**
     * Accept button background color as a hex value. Defaults to '#f54e00'.
     * @pattern ^#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$
     */
    buttonColor?: string
    /**
     * Accept button text color as a hex value. Defaults to '#ffffff'.
     * @pattern ^#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$
     */
    buttonTextColor?: string
    /** Hide the 'Powered by PostHog' notice. Requires the white labelling entitlement on your plan. */
    whiteLabel?: boolean
    /**
     * Label for the link that opens the consent preferences panel. Defaults to 'Manage preferences'.
     * @maxLength 25
     */
    preferencesButtonText?: string
    /** Show a 'Manage preferences' panel where visitors can consent to analytics and marketing cookies separately. Category choices are exposed to your site via the posthog:consent event. Defaults to false. */
    showPreferences?: boolean
    /** When a visitor declines analytics cookies, keep anonymous cookieless analytics (in-memory persistence, nothing stored on the device) instead of stopping tracking entirely. Defaults to false. */
    cookielessFallback?: boolean
    /** Visitors broadcasting the Global Privacy Control signal are treated as declined and never shown the banner. An explicit choice made on your site still takes precedence. Defaults to true. */
    respectGpc?: boolean
    /** Per-language copy overrides keyed by ISO 639 language code (e.g. 'de', 'pt-BR'). The banner picks the visitor's browser language, falling back to the base copy. */
    translations?: CookieBannerAppearanceApiTranslations
}

/**
 * * `engineering` - Engineering
 * * `data` - Data
 * * `product` - Product Management
 * * `founder` - Founder
 * * `leadership` - Leadership
 * * `marketing` - Marketing
 * * `sales` - Sales / Success
 * * `other` - Other
 */
export type RoleAtOrganizationEnumApi = (typeof RoleAtOrganizationEnumApi)[keyof typeof RoleAtOrganizationEnumApi]

export const RoleAtOrganizationEnumApi = {
    Engineering: 'engineering',
    Data: 'data',
    Product: 'product',
    Founder: 'founder',
    Leadership: 'leadership',
    Marketing: 'marketing',
    Sales: 'sales',
    Other: 'other',
} as const

export type BlankEnumApi = (typeof BlankEnumApi)[keyof typeof BlankEnumApi]

export const BlankEnumApi = {
    '': '',
} as const

/**
 * @nullable
 */
export type UserBasicApiHedgehogConfig = { [key: string]: unknown } | null

export interface UserBasicApi {
    readonly id: number
    readonly uuid: string
    /**
     * @maxLength 200
     * @nullable
     */
    distinct_id?: string | null
    /** @maxLength 150 */
    first_name?: string
    /** @maxLength 150 */
    last_name?: string
    /** @maxLength 254 */
    email: string
    /** @nullable */
    is_email_verified?: boolean | null
    /** @nullable */
    readonly hedgehog_config: UserBasicApiHedgehogConfig
    role_at_organization?: RoleAtOrganizationEnumApi | BlankEnumApi | null
}

export interface CookieBannerConfigApi {
    /** Unique id of the banner config. */
    readonly id: string
    /** Whether the banner is served to your website. Defaults to false. */
    enabled?: boolean
    /** Appearance and copy overrides. Omitted keys use the PostHog-styled defaults. */
    appearance?: CookieBannerAppearanceApi
    /** When the banner config was created. */
    readonly created_at: string
    /** User who created the banner. */
    readonly created_by: UserBasicApi
    /** When the banner config was last updated. */
    readonly updated_at: string
}

export interface PaginatedCookieBannerConfigListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: CookieBannerConfigApi[]
}

export interface PatchedCookieBannerConfigApi {
    /** Unique id of the banner config. */
    readonly id?: string
    /** Whether the banner is served to your website. Defaults to false. */
    enabled?: boolean
    /** Appearance and copy overrides. Omitted keys use the PostHog-styled defaults. */
    appearance?: CookieBannerAppearanceApi
    /** When the banner config was created. */
    readonly created_at?: string
    /** User who created the banner. */
    readonly created_by?: UserBasicApi
    /** When the banner config was last updated. */
    readonly updated_at?: string
}

export type CookieBannerListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}
