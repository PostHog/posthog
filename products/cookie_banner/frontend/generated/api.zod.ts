/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * Manage the project's cookie banner. A project has at most one banner,
 * so list returns zero or one items and create fails once one exists.
 */
export const cookieBannerCreateBodyAppearanceOneTitleMax = 25

export const cookieBannerCreateBodyAppearanceOneDescriptionMax = 200

export const cookieBannerCreateBodyAppearanceOneAcceptButtonTextMax = 11

export const cookieBannerCreateBodyAppearanceOneDeclineButtonTextMax = 11

export const cookieBannerCreateBodyAppearanceOneBackgroundColorRegExp = new RegExp(
    '^#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$'
)
export const cookieBannerCreateBodyAppearanceOneTextColorRegExp = new RegExp(
    '^#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$'
)
export const cookieBannerCreateBodyAppearanceOneButtonColorRegExp = new RegExp(
    '^#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$'
)
export const cookieBannerCreateBodyAppearanceOneButtonTextColorRegExp = new RegExp(
    '^#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$'
)
export const cookieBannerCreateBodyAppearanceOnePreferencesButtonTextMax = 25

export const cookieBannerCreateBodyAppearanceOneCategoriesItemKeyRegExp = new RegExp('^[a-z][a-z0-9_-]{0,31}$')
export const cookieBannerCreateBodyAppearanceOneCategoriesItemLabelMax = 30

export const cookieBannerCreateBodyAppearanceOneCategoriesItemDescriptionMax = 120

export const cookieBannerCreateBodyAppearanceOneCategoriesMax = 10

export const cookieBannerCreateBodyAppearanceOneTranslationsTitleMax = 25

export const cookieBannerCreateBodyAppearanceOneTranslationsDescriptionMax = 200

export const cookieBannerCreateBodyAppearanceOneTranslationsAcceptButtonTextMax = 11

export const cookieBannerCreateBodyAppearanceOneTranslationsDeclineButtonTextMax = 11

export const cookieBannerCreateBodyAppearanceOneTranslationsPreferencesButtonTextMax = 25

export const CookieBannerCreateBody = /* @__PURE__ */ zod.object({
    enabled: zod.boolean().optional().describe('Whether the banner is served to your website. Defaults to false.'),
    appearance: zod
        .object({
            title: zod
                .string()
                .max(cookieBannerCreateBodyAppearanceOneTitleMax)
                .optional()
                .describe("Banner headline. Plain text only. Defaults to 'We use cookies'."),
            description: zod
                .string()
                .max(cookieBannerCreateBodyAppearanceOneDescriptionMax)
                .optional()
                .describe('Body copy explaining what cookies are used for. Plain text only.'),
            acceptButtonText: zod
                .string()
                .max(cookieBannerCreateBodyAppearanceOneAcceptButtonTextMax)
                .optional()
                .describe("Label for the button that opts the visitor in to tracking. Defaults to 'Accept'."),
            declineButtonText: zod
                .string()
                .max(cookieBannerCreateBodyAppearanceOneDeclineButtonTextMax)
                .optional()
                .describe("Label for the button that opts the visitor out of tracking. Defaults to 'Decline'."),
            artStyle: zod
                .enum([
                    'none',
                    'posthog-logo',
                    'posthog-logomark-light',
                    'hedgehog-builder',
                    'hedgehog-business',
                    'hedgehog-hogzilla',
                    'hedgehog-robot',
                    'hedgehog-mobile',
                    'hedgehog-zen',
                    'hedgehog-lens',
                    'hedgehog-town-crier',
                    'hedgehog-wizard',
                    'hedgehog-legal',
                ])
                .describe(
                    '\* `none` - none\n\* `posthog-logo` - posthog-logo\n\* `posthog-logomark-light` - posthog-logomark-light\n\* `hedgehog-builder` - hedgehog-builder\n\* `hedgehog-business` - hedgehog-business\n\* `hedgehog-hogzilla` - hedgehog-hogzilla\n\* `hedgehog-robot` - hedgehog-robot\n\* `hedgehog-mobile` - hedgehog-mobile\n\* `hedgehog-zen` - hedgehog-zen\n\* `hedgehog-lens` - hedgehog-lens\n\* `hedgehog-town-crier` - hedgehog-town-crier\n\* `hedgehog-wizard` - hedgehog-wizard\n\* `hedgehog-legal` - hedgehog-legal'
                )
                .optional()
                .describe(
                    "Artwork shown on the banner: the PostHog logo, hedgehog art, or none. Defaults to 'posthog-logo'.\n\n\* `none` - none\n\* `posthog-logo` - posthog-logo\n\* `posthog-logomark-light` - posthog-logomark-light\n\* `hedgehog-builder` - hedgehog-builder\n\* `hedgehog-business` - hedgehog-business\n\* `hedgehog-hogzilla` - hedgehog-hogzilla\n\* `hedgehog-robot` - hedgehog-robot\n\* `hedgehog-mobile` - hedgehog-mobile\n\* `hedgehog-zen` - hedgehog-zen\n\* `hedgehog-lens` - hedgehog-lens\n\* `hedgehog-town-crier` - hedgehog-town-crier\n\* `hedgehog-wizard` - hedgehog-wizard\n\* `hedgehog-legal` - hedgehog-legal"
                ),
            position: zod
                .enum(['bottom-left', 'bottom-right', 'bottom-bar'])
                .describe(
                    '\* `bottom-left` - bottom-left\n\* `bottom-right` - bottom-right\n\* `bottom-bar` - bottom-bar'
                )
                .optional()
                .describe(
                    "Where the banner appears on the page. Defaults to 'bottom-right'.\n\n\* `bottom-left` - bottom-left\n\* `bottom-right` - bottom-right\n\* `bottom-bar` - bottom-bar"
                ),
            backgroundColor: zod
                .string()
                .regex(cookieBannerCreateBodyAppearanceOneBackgroundColorRegExp)
                .optional()
                .describe("Banner background color as a hex value. Defaults to '#eeefe9'."),
            textColor: zod
                .string()
                .regex(cookieBannerCreateBodyAppearanceOneTextColorRegExp)
                .optional()
                .describe("Banner text color as a hex value. Defaults to '#151515'."),
            buttonColor: zod
                .string()
                .regex(cookieBannerCreateBodyAppearanceOneButtonColorRegExp)
                .optional()
                .describe("Accept button background color as a hex value. Defaults to '#f54e00'."),
            buttonTextColor: zod
                .string()
                .regex(cookieBannerCreateBodyAppearanceOneButtonTextColorRegExp)
                .optional()
                .describe("Accept button text color as a hex value. Defaults to '#ffffff'."),
            whiteLabel: zod
                .boolean()
                .optional()
                .describe(
                    "Hide the 'Powered by PostHog' notice. Requires the white labelling entitlement on your plan."
                ),
            preferencesButtonText: zod
                .string()
                .max(cookieBannerCreateBodyAppearanceOnePreferencesButtonTextMax)
                .optional()
                .describe(
                    "Label for the link that opens the consent preferences panel. Defaults to 'Manage preferences'."
                ),
            showPreferences: zod
                .boolean()
                .optional()
                .describe(
                    "Show a 'Manage preferences' panel where visitors can consent to analytics and marketing cookies separately. Category choices are exposed to your site via the posthog:consent event. Defaults to false."
                ),
            cookielessFallback: zod
                .boolean()
                .optional()
                .describe(
                    'When a visitor declines analytics cookies, keep anonymous cookieless analytics (in-memory persistence, nothing stored on the device) instead of stopping tracking entirely. Defaults to false.'
                ),
            respectGpc: zod
                .boolean()
                .optional()
                .describe(
                    'Visitors broadcasting the Global Privacy Control signal are treated as declined and never shown the banner. An explicit choice made on your site still takes precedence. Defaults to true.'
                ),
            googleConsentMode: zod
                .boolean()
                .optional()
                .describe(
                    "Push Google Consent Mode v2 signals: a denied default before any Google tag runs, then an update on the visitor's choice (analytics_storage from the analytics category; ad_storage, ad_user_data and ad_personalization from the marketing category). Defaults to false."
                ),
            categories: zod
                .array(
                    zod
                        .object({
                            key: zod
                                .string()
                                .regex(cookieBannerCreateBodyAppearanceOneCategoriesItemKeyRegExp)
                                .describe(
                                    "Category identifier used in data-ph-consent attributes and the posthog:consent event: lowercase letters, digits, '-' or '_', starting with a letter (e.g. 'marketing')."
                                ),
                            label: zod
                                .string()
                                .max(cookieBannerCreateBodyAppearanceOneCategoriesItemLabelMax)
                                .describe("Name of the category shown in the banner's preferences panel."),
                            description: zod
                                .string()
                                .max(cookieBannerCreateBodyAppearanceOneCategoriesItemDescriptionMax)
                                .optional()
                                .describe(
                                    'Optional one-line explanation shown under the category in the preferences panel.'
                                ),
                        })
                        .describe(
                            'A consent category visitors can grant or deny individually. `necessary` is\nimplicit and always-on; `analytics` is required and drives PostHog tracking consent.'
                        )
                )
                .max(cookieBannerCreateBodyAppearanceOneCategoriesMax)
                .optional()
                .describe(
                    "Consent categories visitors can grant or deny in the preferences panel and target with data-ph-consent script attributes. Must include 'analytics' (drives PostHog tracking consent); 'necessary' is implicit and always-on. Defaults to Analytics and Marketing."
                ),
            translations: zod
                .record(
                    zod.string(),
                    zod
                        .object({
                            title: zod
                                .string()
                                .max(cookieBannerCreateBodyAppearanceOneTranslationsTitleMax)
                                .optional()
                                .describe('Translated banner headline.'),
                            description: zod
                                .string()
                                .max(cookieBannerCreateBodyAppearanceOneTranslationsDescriptionMax)
                                .optional()
                                .describe('Translated body copy.'),
                            acceptButtonText: zod
                                .string()
                                .max(cookieBannerCreateBodyAppearanceOneTranslationsAcceptButtonTextMax)
                                .optional()
                                .describe('Translated accept button label.'),
                            declineButtonText: zod
                                .string()
                                .max(cookieBannerCreateBodyAppearanceOneTranslationsDeclineButtonTextMax)
                                .optional()
                                .describe('Translated decline button label.'),
                            preferencesButtonText: zod
                                .string()
                                .max(cookieBannerCreateBodyAppearanceOneTranslationsPreferencesButtonTextMax)
                                .optional()
                                .describe("Translated 'Manage preferences' label."),
                        })
                        .describe(
                            'Per-language overrides for the banner copy. Omitted keys fall back to the base\n(untranslated) copy for visitors matching this language.'
                        )
                )
                .optional()
                .describe(
                    "Per-language copy overrides keyed by ISO 639 language code (e.g. 'de', 'pt-BR'). The banner picks the visitor's browser language, falling back to the base copy."
                ),
        })
        .describe(
            'Appearance overrides for the banner. Omitted keys fall back to the PostHog-styled defaults\n(see products\/cookie_banner\/backend\/constants.py) when the banner is delivered.'
        )
        .optional()
        .describe('Appearance and copy overrides. Omitted keys use the PostHog-styled defaults.'),
})

/**
 * Manage the project's cookie banner. A project has at most one banner,
 * so list returns zero or one items and create fails once one exists.
 */
export const cookieBannerUpdateBodyAppearanceOneTitleMax = 25

export const cookieBannerUpdateBodyAppearanceOneDescriptionMax = 200

export const cookieBannerUpdateBodyAppearanceOneAcceptButtonTextMax = 11

export const cookieBannerUpdateBodyAppearanceOneDeclineButtonTextMax = 11

export const cookieBannerUpdateBodyAppearanceOneBackgroundColorRegExp = new RegExp(
    '^#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$'
)
export const cookieBannerUpdateBodyAppearanceOneTextColorRegExp = new RegExp(
    '^#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$'
)
export const cookieBannerUpdateBodyAppearanceOneButtonColorRegExp = new RegExp(
    '^#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$'
)
export const cookieBannerUpdateBodyAppearanceOneButtonTextColorRegExp = new RegExp(
    '^#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$'
)
export const cookieBannerUpdateBodyAppearanceOnePreferencesButtonTextMax = 25

export const cookieBannerUpdateBodyAppearanceOneCategoriesItemKeyRegExp = new RegExp('^[a-z][a-z0-9_-]{0,31}$')
export const cookieBannerUpdateBodyAppearanceOneCategoriesItemLabelMax = 30

export const cookieBannerUpdateBodyAppearanceOneCategoriesItemDescriptionMax = 120

export const cookieBannerUpdateBodyAppearanceOneCategoriesMax = 10

export const cookieBannerUpdateBodyAppearanceOneTranslationsTitleMax = 25

export const cookieBannerUpdateBodyAppearanceOneTranslationsDescriptionMax = 200

export const cookieBannerUpdateBodyAppearanceOneTranslationsAcceptButtonTextMax = 11

export const cookieBannerUpdateBodyAppearanceOneTranslationsDeclineButtonTextMax = 11

export const cookieBannerUpdateBodyAppearanceOneTranslationsPreferencesButtonTextMax = 25

export const CookieBannerUpdateBody = /* @__PURE__ */ zod.object({
    enabled: zod.boolean().optional().describe('Whether the banner is served to your website. Defaults to false.'),
    appearance: zod
        .object({
            title: zod
                .string()
                .max(cookieBannerUpdateBodyAppearanceOneTitleMax)
                .optional()
                .describe("Banner headline. Plain text only. Defaults to 'We use cookies'."),
            description: zod
                .string()
                .max(cookieBannerUpdateBodyAppearanceOneDescriptionMax)
                .optional()
                .describe('Body copy explaining what cookies are used for. Plain text only.'),
            acceptButtonText: zod
                .string()
                .max(cookieBannerUpdateBodyAppearanceOneAcceptButtonTextMax)
                .optional()
                .describe("Label for the button that opts the visitor in to tracking. Defaults to 'Accept'."),
            declineButtonText: zod
                .string()
                .max(cookieBannerUpdateBodyAppearanceOneDeclineButtonTextMax)
                .optional()
                .describe("Label for the button that opts the visitor out of tracking. Defaults to 'Decline'."),
            artStyle: zod
                .enum([
                    'none',
                    'posthog-logo',
                    'posthog-logomark-light',
                    'hedgehog-builder',
                    'hedgehog-business',
                    'hedgehog-hogzilla',
                    'hedgehog-robot',
                    'hedgehog-mobile',
                    'hedgehog-zen',
                    'hedgehog-lens',
                    'hedgehog-town-crier',
                    'hedgehog-wizard',
                    'hedgehog-legal',
                ])
                .describe(
                    '\* `none` - none\n\* `posthog-logo` - posthog-logo\n\* `posthog-logomark-light` - posthog-logomark-light\n\* `hedgehog-builder` - hedgehog-builder\n\* `hedgehog-business` - hedgehog-business\n\* `hedgehog-hogzilla` - hedgehog-hogzilla\n\* `hedgehog-robot` - hedgehog-robot\n\* `hedgehog-mobile` - hedgehog-mobile\n\* `hedgehog-zen` - hedgehog-zen\n\* `hedgehog-lens` - hedgehog-lens\n\* `hedgehog-town-crier` - hedgehog-town-crier\n\* `hedgehog-wizard` - hedgehog-wizard\n\* `hedgehog-legal` - hedgehog-legal'
                )
                .optional()
                .describe(
                    "Artwork shown on the banner: the PostHog logo, hedgehog art, or none. Defaults to 'posthog-logo'.\n\n\* `none` - none\n\* `posthog-logo` - posthog-logo\n\* `posthog-logomark-light` - posthog-logomark-light\n\* `hedgehog-builder` - hedgehog-builder\n\* `hedgehog-business` - hedgehog-business\n\* `hedgehog-hogzilla` - hedgehog-hogzilla\n\* `hedgehog-robot` - hedgehog-robot\n\* `hedgehog-mobile` - hedgehog-mobile\n\* `hedgehog-zen` - hedgehog-zen\n\* `hedgehog-lens` - hedgehog-lens\n\* `hedgehog-town-crier` - hedgehog-town-crier\n\* `hedgehog-wizard` - hedgehog-wizard\n\* `hedgehog-legal` - hedgehog-legal"
                ),
            position: zod
                .enum(['bottom-left', 'bottom-right', 'bottom-bar'])
                .describe(
                    '\* `bottom-left` - bottom-left\n\* `bottom-right` - bottom-right\n\* `bottom-bar` - bottom-bar'
                )
                .optional()
                .describe(
                    "Where the banner appears on the page. Defaults to 'bottom-right'.\n\n\* `bottom-left` - bottom-left\n\* `bottom-right` - bottom-right\n\* `bottom-bar` - bottom-bar"
                ),
            backgroundColor: zod
                .string()
                .regex(cookieBannerUpdateBodyAppearanceOneBackgroundColorRegExp)
                .optional()
                .describe("Banner background color as a hex value. Defaults to '#eeefe9'."),
            textColor: zod
                .string()
                .regex(cookieBannerUpdateBodyAppearanceOneTextColorRegExp)
                .optional()
                .describe("Banner text color as a hex value. Defaults to '#151515'."),
            buttonColor: zod
                .string()
                .regex(cookieBannerUpdateBodyAppearanceOneButtonColorRegExp)
                .optional()
                .describe("Accept button background color as a hex value. Defaults to '#f54e00'."),
            buttonTextColor: zod
                .string()
                .regex(cookieBannerUpdateBodyAppearanceOneButtonTextColorRegExp)
                .optional()
                .describe("Accept button text color as a hex value. Defaults to '#ffffff'."),
            whiteLabel: zod
                .boolean()
                .optional()
                .describe(
                    "Hide the 'Powered by PostHog' notice. Requires the white labelling entitlement on your plan."
                ),
            preferencesButtonText: zod
                .string()
                .max(cookieBannerUpdateBodyAppearanceOnePreferencesButtonTextMax)
                .optional()
                .describe(
                    "Label for the link that opens the consent preferences panel. Defaults to 'Manage preferences'."
                ),
            showPreferences: zod
                .boolean()
                .optional()
                .describe(
                    "Show a 'Manage preferences' panel where visitors can consent to analytics and marketing cookies separately. Category choices are exposed to your site via the posthog:consent event. Defaults to false."
                ),
            cookielessFallback: zod
                .boolean()
                .optional()
                .describe(
                    'When a visitor declines analytics cookies, keep anonymous cookieless analytics (in-memory persistence, nothing stored on the device) instead of stopping tracking entirely. Defaults to false.'
                ),
            respectGpc: zod
                .boolean()
                .optional()
                .describe(
                    'Visitors broadcasting the Global Privacy Control signal are treated as declined and never shown the banner. An explicit choice made on your site still takes precedence. Defaults to true.'
                ),
            googleConsentMode: zod
                .boolean()
                .optional()
                .describe(
                    "Push Google Consent Mode v2 signals: a denied default before any Google tag runs, then an update on the visitor's choice (analytics_storage from the analytics category; ad_storage, ad_user_data and ad_personalization from the marketing category). Defaults to false."
                ),
            categories: zod
                .array(
                    zod
                        .object({
                            key: zod
                                .string()
                                .regex(cookieBannerUpdateBodyAppearanceOneCategoriesItemKeyRegExp)
                                .describe(
                                    "Category identifier used in data-ph-consent attributes and the posthog:consent event: lowercase letters, digits, '-' or '_', starting with a letter (e.g. 'marketing')."
                                ),
                            label: zod
                                .string()
                                .max(cookieBannerUpdateBodyAppearanceOneCategoriesItemLabelMax)
                                .describe("Name of the category shown in the banner's preferences panel."),
                            description: zod
                                .string()
                                .max(cookieBannerUpdateBodyAppearanceOneCategoriesItemDescriptionMax)
                                .optional()
                                .describe(
                                    'Optional one-line explanation shown under the category in the preferences panel.'
                                ),
                        })
                        .describe(
                            'A consent category visitors can grant or deny individually. `necessary` is\nimplicit and always-on; `analytics` is required and drives PostHog tracking consent.'
                        )
                )
                .max(cookieBannerUpdateBodyAppearanceOneCategoriesMax)
                .optional()
                .describe(
                    "Consent categories visitors can grant or deny in the preferences panel and target with data-ph-consent script attributes. Must include 'analytics' (drives PostHog tracking consent); 'necessary' is implicit and always-on. Defaults to Analytics and Marketing."
                ),
            translations: zod
                .record(
                    zod.string(),
                    zod
                        .object({
                            title: zod
                                .string()
                                .max(cookieBannerUpdateBodyAppearanceOneTranslationsTitleMax)
                                .optional()
                                .describe('Translated banner headline.'),
                            description: zod
                                .string()
                                .max(cookieBannerUpdateBodyAppearanceOneTranslationsDescriptionMax)
                                .optional()
                                .describe('Translated body copy.'),
                            acceptButtonText: zod
                                .string()
                                .max(cookieBannerUpdateBodyAppearanceOneTranslationsAcceptButtonTextMax)
                                .optional()
                                .describe('Translated accept button label.'),
                            declineButtonText: zod
                                .string()
                                .max(cookieBannerUpdateBodyAppearanceOneTranslationsDeclineButtonTextMax)
                                .optional()
                                .describe('Translated decline button label.'),
                            preferencesButtonText: zod
                                .string()
                                .max(cookieBannerUpdateBodyAppearanceOneTranslationsPreferencesButtonTextMax)
                                .optional()
                                .describe("Translated 'Manage preferences' label."),
                        })
                        .describe(
                            'Per-language overrides for the banner copy. Omitted keys fall back to the base\n(untranslated) copy for visitors matching this language.'
                        )
                )
                .optional()
                .describe(
                    "Per-language copy overrides keyed by ISO 639 language code (e.g. 'de', 'pt-BR'). The banner picks the visitor's browser language, falling back to the base copy."
                ),
        })
        .describe(
            'Appearance overrides for the banner. Omitted keys fall back to the PostHog-styled defaults\n(see products\/cookie_banner\/backend\/constants.py) when the banner is delivered.'
        )
        .optional()
        .describe('Appearance and copy overrides. Omitted keys use the PostHog-styled defaults.'),
})

/**
 * Manage the project's cookie banner. A project has at most one banner,
 * so list returns zero or one items and create fails once one exists.
 */
export const cookieBannerPartialUpdateBodyAppearanceOneTitleMax = 25

export const cookieBannerPartialUpdateBodyAppearanceOneDescriptionMax = 200

export const cookieBannerPartialUpdateBodyAppearanceOneAcceptButtonTextMax = 11

export const cookieBannerPartialUpdateBodyAppearanceOneDeclineButtonTextMax = 11

export const cookieBannerPartialUpdateBodyAppearanceOneBackgroundColorRegExp = new RegExp(
    '^#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$'
)
export const cookieBannerPartialUpdateBodyAppearanceOneTextColorRegExp = new RegExp(
    '^#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$'
)
export const cookieBannerPartialUpdateBodyAppearanceOneButtonColorRegExp = new RegExp(
    '^#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$'
)
export const cookieBannerPartialUpdateBodyAppearanceOneButtonTextColorRegExp = new RegExp(
    '^#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$'
)
export const cookieBannerPartialUpdateBodyAppearanceOnePreferencesButtonTextMax = 25

export const cookieBannerPartialUpdateBodyAppearanceOneCategoriesItemKeyRegExp = new RegExp('^[a-z][a-z0-9_-]{0,31}$')
export const cookieBannerPartialUpdateBodyAppearanceOneCategoriesItemLabelMax = 30

export const cookieBannerPartialUpdateBodyAppearanceOneCategoriesItemDescriptionMax = 120

export const cookieBannerPartialUpdateBodyAppearanceOneCategoriesMax = 10

export const cookieBannerPartialUpdateBodyAppearanceOneTranslationsTitleMax = 25

export const cookieBannerPartialUpdateBodyAppearanceOneTranslationsDescriptionMax = 200

export const cookieBannerPartialUpdateBodyAppearanceOneTranslationsAcceptButtonTextMax = 11

export const cookieBannerPartialUpdateBodyAppearanceOneTranslationsDeclineButtonTextMax = 11

export const cookieBannerPartialUpdateBodyAppearanceOneTranslationsPreferencesButtonTextMax = 25

export const CookieBannerPartialUpdateBody = /* @__PURE__ */ zod.object({
    enabled: zod.boolean().optional().describe('Whether the banner is served to your website. Defaults to false.'),
    appearance: zod
        .object({
            title: zod
                .string()
                .max(cookieBannerPartialUpdateBodyAppearanceOneTitleMax)
                .optional()
                .describe("Banner headline. Plain text only. Defaults to 'We use cookies'."),
            description: zod
                .string()
                .max(cookieBannerPartialUpdateBodyAppearanceOneDescriptionMax)
                .optional()
                .describe('Body copy explaining what cookies are used for. Plain text only.'),
            acceptButtonText: zod
                .string()
                .max(cookieBannerPartialUpdateBodyAppearanceOneAcceptButtonTextMax)
                .optional()
                .describe("Label for the button that opts the visitor in to tracking. Defaults to 'Accept'."),
            declineButtonText: zod
                .string()
                .max(cookieBannerPartialUpdateBodyAppearanceOneDeclineButtonTextMax)
                .optional()
                .describe("Label for the button that opts the visitor out of tracking. Defaults to 'Decline'."),
            artStyle: zod
                .enum([
                    'none',
                    'posthog-logo',
                    'posthog-logomark-light',
                    'hedgehog-builder',
                    'hedgehog-business',
                    'hedgehog-hogzilla',
                    'hedgehog-robot',
                    'hedgehog-mobile',
                    'hedgehog-zen',
                    'hedgehog-lens',
                    'hedgehog-town-crier',
                    'hedgehog-wizard',
                    'hedgehog-legal',
                ])
                .describe(
                    '\* `none` - none\n\* `posthog-logo` - posthog-logo\n\* `posthog-logomark-light` - posthog-logomark-light\n\* `hedgehog-builder` - hedgehog-builder\n\* `hedgehog-business` - hedgehog-business\n\* `hedgehog-hogzilla` - hedgehog-hogzilla\n\* `hedgehog-robot` - hedgehog-robot\n\* `hedgehog-mobile` - hedgehog-mobile\n\* `hedgehog-zen` - hedgehog-zen\n\* `hedgehog-lens` - hedgehog-lens\n\* `hedgehog-town-crier` - hedgehog-town-crier\n\* `hedgehog-wizard` - hedgehog-wizard\n\* `hedgehog-legal` - hedgehog-legal'
                )
                .optional()
                .describe(
                    "Artwork shown on the banner: the PostHog logo, hedgehog art, or none. Defaults to 'posthog-logo'.\n\n\* `none` - none\n\* `posthog-logo` - posthog-logo\n\* `posthog-logomark-light` - posthog-logomark-light\n\* `hedgehog-builder` - hedgehog-builder\n\* `hedgehog-business` - hedgehog-business\n\* `hedgehog-hogzilla` - hedgehog-hogzilla\n\* `hedgehog-robot` - hedgehog-robot\n\* `hedgehog-mobile` - hedgehog-mobile\n\* `hedgehog-zen` - hedgehog-zen\n\* `hedgehog-lens` - hedgehog-lens\n\* `hedgehog-town-crier` - hedgehog-town-crier\n\* `hedgehog-wizard` - hedgehog-wizard\n\* `hedgehog-legal` - hedgehog-legal"
                ),
            position: zod
                .enum(['bottom-left', 'bottom-right', 'bottom-bar'])
                .describe(
                    '\* `bottom-left` - bottom-left\n\* `bottom-right` - bottom-right\n\* `bottom-bar` - bottom-bar'
                )
                .optional()
                .describe(
                    "Where the banner appears on the page. Defaults to 'bottom-right'.\n\n\* `bottom-left` - bottom-left\n\* `bottom-right` - bottom-right\n\* `bottom-bar` - bottom-bar"
                ),
            backgroundColor: zod
                .string()
                .regex(cookieBannerPartialUpdateBodyAppearanceOneBackgroundColorRegExp)
                .optional()
                .describe("Banner background color as a hex value. Defaults to '#eeefe9'."),
            textColor: zod
                .string()
                .regex(cookieBannerPartialUpdateBodyAppearanceOneTextColorRegExp)
                .optional()
                .describe("Banner text color as a hex value. Defaults to '#151515'."),
            buttonColor: zod
                .string()
                .regex(cookieBannerPartialUpdateBodyAppearanceOneButtonColorRegExp)
                .optional()
                .describe("Accept button background color as a hex value. Defaults to '#f54e00'."),
            buttonTextColor: zod
                .string()
                .regex(cookieBannerPartialUpdateBodyAppearanceOneButtonTextColorRegExp)
                .optional()
                .describe("Accept button text color as a hex value. Defaults to '#ffffff'."),
            whiteLabel: zod
                .boolean()
                .optional()
                .describe(
                    "Hide the 'Powered by PostHog' notice. Requires the white labelling entitlement on your plan."
                ),
            preferencesButtonText: zod
                .string()
                .max(cookieBannerPartialUpdateBodyAppearanceOnePreferencesButtonTextMax)
                .optional()
                .describe(
                    "Label for the link that opens the consent preferences panel. Defaults to 'Manage preferences'."
                ),
            showPreferences: zod
                .boolean()
                .optional()
                .describe(
                    "Show a 'Manage preferences' panel where visitors can consent to analytics and marketing cookies separately. Category choices are exposed to your site via the posthog:consent event. Defaults to false."
                ),
            cookielessFallback: zod
                .boolean()
                .optional()
                .describe(
                    'When a visitor declines analytics cookies, keep anonymous cookieless analytics (in-memory persistence, nothing stored on the device) instead of stopping tracking entirely. Defaults to false.'
                ),
            respectGpc: zod
                .boolean()
                .optional()
                .describe(
                    'Visitors broadcasting the Global Privacy Control signal are treated as declined and never shown the banner. An explicit choice made on your site still takes precedence. Defaults to true.'
                ),
            googleConsentMode: zod
                .boolean()
                .optional()
                .describe(
                    "Push Google Consent Mode v2 signals: a denied default before any Google tag runs, then an update on the visitor's choice (analytics_storage from the analytics category; ad_storage, ad_user_data and ad_personalization from the marketing category). Defaults to false."
                ),
            categories: zod
                .array(
                    zod
                        .object({
                            key: zod
                                .string()
                                .regex(cookieBannerPartialUpdateBodyAppearanceOneCategoriesItemKeyRegExp)
                                .describe(
                                    "Category identifier used in data-ph-consent attributes and the posthog:consent event: lowercase letters, digits, '-' or '_', starting with a letter (e.g. 'marketing')."
                                ),
                            label: zod
                                .string()
                                .max(cookieBannerPartialUpdateBodyAppearanceOneCategoriesItemLabelMax)
                                .describe("Name of the category shown in the banner's preferences panel."),
                            description: zod
                                .string()
                                .max(cookieBannerPartialUpdateBodyAppearanceOneCategoriesItemDescriptionMax)
                                .optional()
                                .describe(
                                    'Optional one-line explanation shown under the category in the preferences panel.'
                                ),
                        })
                        .describe(
                            'A consent category visitors can grant or deny individually. `necessary` is\nimplicit and always-on; `analytics` is required and drives PostHog tracking consent.'
                        )
                )
                .max(cookieBannerPartialUpdateBodyAppearanceOneCategoriesMax)
                .optional()
                .describe(
                    "Consent categories visitors can grant or deny in the preferences panel and target with data-ph-consent script attributes. Must include 'analytics' (drives PostHog tracking consent); 'necessary' is implicit and always-on. Defaults to Analytics and Marketing."
                ),
            translations: zod
                .record(
                    zod.string(),
                    zod
                        .object({
                            title: zod
                                .string()
                                .max(cookieBannerPartialUpdateBodyAppearanceOneTranslationsTitleMax)
                                .optional()
                                .describe('Translated banner headline.'),
                            description: zod
                                .string()
                                .max(cookieBannerPartialUpdateBodyAppearanceOneTranslationsDescriptionMax)
                                .optional()
                                .describe('Translated body copy.'),
                            acceptButtonText: zod
                                .string()
                                .max(cookieBannerPartialUpdateBodyAppearanceOneTranslationsAcceptButtonTextMax)
                                .optional()
                                .describe('Translated accept button label.'),
                            declineButtonText: zod
                                .string()
                                .max(cookieBannerPartialUpdateBodyAppearanceOneTranslationsDeclineButtonTextMax)
                                .optional()
                                .describe('Translated decline button label.'),
                            preferencesButtonText: zod
                                .string()
                                .max(cookieBannerPartialUpdateBodyAppearanceOneTranslationsPreferencesButtonTextMax)
                                .optional()
                                .describe("Translated 'Manage preferences' label."),
                        })
                        .describe(
                            'Per-language overrides for the banner copy. Omitted keys fall back to the base\n(untranslated) copy for visitors matching this language.'
                        )
                )
                .optional()
                .describe(
                    "Per-language copy overrides keyed by ISO 639 language code (e.g. 'de', 'pt-BR'). The banner picks the visitor's browser language, falling back to the base copy."
                ),
        })
        .describe(
            'Appearance overrides for the banner. Omitted keys fall back to the PostHog-styled defaults\n(see products\/cookie_banner\/backend\/constants.py) when the banner is delivered.'
        )
        .optional()
        .describe('Appearance and copy overrides. Omitted keys use the PostHog-styled defaults.'),
})
