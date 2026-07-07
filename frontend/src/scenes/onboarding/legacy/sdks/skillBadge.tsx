import { IconCode } from '@posthog/icons'

import { SDKKey, type SDK } from '~/types'

import { ALL_SDKS } from './allSDKs'

/**
 * Every framework the wizard CLI ships under `src/frameworks/`. The CLI sends
 * one of these strings as `skill_id` on the wizard session. Kept here (not on
 * the CLI side) so we can drive the storybook picker and the alias map below
 * from a single source of truth — keep this in sync with the CLI repo.
 */
export const WIZARD_SKILL_IDS = [
    'android',
    'angular',
    'astro',
    'django',
    'fastapi',
    'flask',
    'javascript-node',
    'javascript-web',
    'laravel',
    'nextjs',
    'nuxt',
    'python',
    'rails',
    'react-native',
    'react-router',
    'ruby',
    'svelte',
    'swift',
    'tanstack-router',
    'tanstack-start',
    'vue',
] as const

/**
 * Wizard `skill_id` → PostHog SDKKey. The CLI uses hyphenated framework names
 * (`react-native`) while PostHog's SDK catalogue uses underscored enum keys
 * (`react_native`), and a handful of frameworks don't map 1:1 — this table
 * resolves both kinds of divergence.
 */
const WIZARD_SKILL_TO_SDK_KEY: Record<string, SDKKey> = {
    android: SDKKey.ANDROID,
    angular: SDKKey.ANGULAR,
    astro: SDKKey.ASTRO,
    django: SDKKey.DJANGO,
    'javascript-node': SDKKey.NODE_JS,
    'javascript-web': SDKKey.JS_WEB,
    laravel: SDKKey.LARAVEL,
    nextjs: SDKKey.NEXT_JS,
    nuxt: SDKKey.NUXT_JS,
    python: SDKKey.PYTHON,
    rails: SDKKey.RUBY_ON_RAILS,
    'react-native': SDKKey.REACT_NATIVE,
    'react-router': SDKKey.REACT_ROUTER,
    ruby: SDKKey.RUBY,
    svelte: SDKKey.SVELTE,
    swift: SDKKey.IOS,
    'tanstack-start': SDKKey.TANSTACK_START,
    vue: SDKKey.VUE_JS,
    // No PostHog SDK match yet — fastapi, flask, tanstack-router fall through to
    // the IconCode placeholder + tidied display name.
}

/**
 * Look up an SDK entry by a wizard `skill_id`. Tries the alias map first, then
 * a direct match on SDKKey value, then a normalized underscore form. Returns
 * `null` for unknown ids; callers should fall back gracefully.
 */
export function findSdkByKey(skillId: string): SDK | null {
    const mappedKey = WIZARD_SKILL_TO_SDK_KEY[skillId]
    if (mappedKey) {
        const sdk = ALL_SDKS.find((s) => s.key === mappedKey)
        if (sdk) {
            return sdk
        }
    }
    const direct = ALL_SDKS.find((s) => s.key === skillId)
    if (direct) {
        return direct
    }
    const normalized = skillId.replace(/-/g, '_')
    if (normalized !== skillId) {
        return ALL_SDKS.find((s) => s.key === normalized) ?? null
    }
    return null
}

/**
 * Human-readable name for a skill_id. Uses the canonical SDK name when known
 * (`laravel → Laravel`, `react-native → React Native`) and falls back to a
 * tidied-up version of the raw id (`fastapi → Fastapi`).
 */
export function getSkillDisplayName(skillId: string): string {
    const sdk = findSdkByKey(skillId)
    if (sdk) {
        return sdk.name
    }
    return skillId.charAt(0).toUpperCase() + skillId.slice(1).replace(/[_-]/g, ' ')
}

/**
 * Inline logo + display name for a wizard skill_id. Use anywhere a wizard
 * session needs to be visually identified (progress panel, FAB, logs, etc.).
 *
 * Unknown skills fall back to a generic code icon plus a tidied display name.
 */
export function SkillBadge({
    skillId,
    size = 16,
    className,
}: {
    skillId: string
    /** Logo edge length in px (also used for the fallback icon). Defaults to 16. */
    size?: number
    /** Extra classes for the wrapper. */
    className?: string
}): JSX.Element {
    const sdk = findSdkByKey(skillId)
    const displayName = sdk?.name ?? getSkillDisplayName(skillId)
    return (
        <span className={`inline-flex items-center gap-1.5 ${className ?? ''}`.trim()}>
            <SkillLogoImage sdk={sdk} alt={`${displayName} logo`} size={size} />
            <span>{displayName}</span>
        </span>
    )
}

/**
 * Just the logo — useful when the framework name is in the surrounding copy and
 * the inline `SkillBadge` wrapper would be redundant.
 */
export function SkillLogo({
    skillId,
    size = 16,
    className,
}: {
    skillId: string
    size?: number
    className?: string
}): JSX.Element {
    const sdk = findSdkByKey(skillId)
    const displayName = sdk?.name ?? getSkillDisplayName(skillId)
    return <SkillLogoImage sdk={sdk} alt={`${displayName} logo`} size={size} className={className} />
}

function SkillLogoImage({
    sdk,
    alt,
    size,
    className,
}: {
    sdk: SDK | null
    alt: string
    size: number
    className?: string
}): JSX.Element {
    const sizeStyle = { width: size, height: size }
    const extra = className ?? ''
    if (!sdk) {
        return (
            <span
                style={sizeStyle}
                className={`inline-flex items-center justify-center text-muted shrink-0 ${extra}`.trim()}
            >
                <IconCode style={sizeStyle} aria-hidden />
            </span>
        )
    }
    const image = sdk.image
    if (typeof image === 'string') {
        return <img src={image} alt={alt} style={sizeStyle} className={`object-contain shrink-0 ${extra}`.trim()} />
    }
    if (typeof image === 'object' && image !== null && 'default' in image) {
        return (
            <img
                src={image.default}
                alt={alt}
                style={sizeStyle}
                className={`object-contain shrink-0 ${extra}`.trim()}
            />
        )
    }
    // React element (custom logo component). It draws into its own container; constrain via CSS.
    return (
        <span style={sizeStyle} className={`inline-flex items-center justify-center shrink-0 ${extra}`.trim()}>
            {image}
        </span>
    )
}
