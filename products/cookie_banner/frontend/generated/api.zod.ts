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
export const cookieBannerCreateBodyAppearanceOneTitleMax = 200

export const cookieBannerCreateBodyAppearanceOneDescriptionMax = 1000

export const cookieBannerCreateBodyAppearanceOneAcceptButtonTextMax = 100

export const cookieBannerCreateBodyAppearanceOneDeclineButtonTextMax = 100

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
                ])
                .describe(
                    '\* `none` - none\n\* `posthog-logo` - posthog-logo\n\* `posthog-logomark-light` - posthog-logomark-light\n\* `hedgehog-builder` - hedgehog-builder\n\* `hedgehog-business` - hedgehog-business\n\* `hedgehog-hogzilla` - hedgehog-hogzilla\n\* `hedgehog-robot` - hedgehog-robot'
                )
                .optional()
                .describe(
                    "Artwork shown on the banner: the PostHog logo, hedgehog art, or none. Defaults to 'posthog-logo'.\n\n\* `none` - none\n\* `posthog-logo` - posthog-logo\n\* `posthog-logomark-light` - posthog-logomark-light\n\* `hedgehog-builder` - hedgehog-builder\n\* `hedgehog-business` - hedgehog-business\n\* `hedgehog-hogzilla` - hedgehog-hogzilla\n\* `hedgehog-robot` - hedgehog-robot"
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
export const cookieBannerUpdateBodyAppearanceOneTitleMax = 200

export const cookieBannerUpdateBodyAppearanceOneDescriptionMax = 1000

export const cookieBannerUpdateBodyAppearanceOneAcceptButtonTextMax = 100

export const cookieBannerUpdateBodyAppearanceOneDeclineButtonTextMax = 100

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
                ])
                .describe(
                    '\* `none` - none\n\* `posthog-logo` - posthog-logo\n\* `posthog-logomark-light` - posthog-logomark-light\n\* `hedgehog-builder` - hedgehog-builder\n\* `hedgehog-business` - hedgehog-business\n\* `hedgehog-hogzilla` - hedgehog-hogzilla\n\* `hedgehog-robot` - hedgehog-robot'
                )
                .optional()
                .describe(
                    "Artwork shown on the banner: the PostHog logo, hedgehog art, or none. Defaults to 'posthog-logo'.\n\n\* `none` - none\n\* `posthog-logo` - posthog-logo\n\* `posthog-logomark-light` - posthog-logomark-light\n\* `hedgehog-builder` - hedgehog-builder\n\* `hedgehog-business` - hedgehog-business\n\* `hedgehog-hogzilla` - hedgehog-hogzilla\n\* `hedgehog-robot` - hedgehog-robot"
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
export const cookieBannerPartialUpdateBodyAppearanceOneTitleMax = 200

export const cookieBannerPartialUpdateBodyAppearanceOneDescriptionMax = 1000

export const cookieBannerPartialUpdateBodyAppearanceOneAcceptButtonTextMax = 100

export const cookieBannerPartialUpdateBodyAppearanceOneDeclineButtonTextMax = 100

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
                ])
                .describe(
                    '\* `none` - none\n\* `posthog-logo` - posthog-logo\n\* `posthog-logomark-light` - posthog-logomark-light\n\* `hedgehog-builder` - hedgehog-builder\n\* `hedgehog-business` - hedgehog-business\n\* `hedgehog-hogzilla` - hedgehog-hogzilla\n\* `hedgehog-robot` - hedgehog-robot'
                )
                .optional()
                .describe(
                    "Artwork shown on the banner: the PostHog logo, hedgehog art, or none. Defaults to 'posthog-logo'.\n\n\* `none` - none\n\* `posthog-logo` - posthog-logo\n\* `posthog-logomark-light` - posthog-logomark-light\n\* `hedgehog-builder` - hedgehog-builder\n\* `hedgehog-business` - hedgehog-business\n\* `hedgehog-hogzilla` - hedgehog-hogzilla\n\* `hedgehog-robot` - hedgehog-robot"
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
        })
        .describe(
            'Appearance overrides for the banner. Omitted keys fall back to the PostHog-styled defaults\n(see products\/cookie_banner\/backend\/constants.py) when the banner is delivered.'
        )
        .optional()
        .describe('Appearance and copy overrides. Omitted keys use the PostHog-styled defaults.'),
})
