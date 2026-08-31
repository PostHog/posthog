import type { LogicWrapper } from 'kea'
import type { ComponentType, CSSProperties, ReactNode } from 'react'

import type { FeatureFlagKey } from 'lib/constants'

import type { ProductKey } from '~/queries/schema/schema-general'
import type { AccessControlLevel, AccessControlResourceType } from '~/types'

/**
 * Normalized setup status for a product, pushed into `productSetupStatusLogic`
 * by the product's own detection logic (data-existence query, exists API, opt-in
 * flag, or entity count). This is the single vocabulary every surface reads.
 *
 * `unknown` means detection failed and no earlier answer exists - surfaces must
 * fail open (render the real product, never a spinner or the setup screen).
 */
export type ProductSetupStatus = 'loading' | 'unknown' | 'needs-setup' | 'waiting-for-data' | 'has-data'

/** The two empty-state variants. `waiting-for-data` is for products with an "installed but no traffic yet" middle state. */
export type ProductEmptyStateMode = 'needs-setup' | 'waiting-for-data'

export interface ProductEmptyStateText {
    /** Sentence case, benefit-first, e.g. "Know how agents actually use your tools" */
    headline: string
    lead: ReactNode
    /**
     * Small line introducing the install command or primary action, e.g. "Fastest way in - our
     * wizard wires up the SDK for you:". It only renders when the mode has one of those under it.
     */
    hint?: ReactNode
}

/**
 * Text keyed by mode: `needs-setup` is the base every product provides; other
 * modes override only the fields that change and fall back to the base for the
 * rest. Binary products (no intermediate state) just provide the base.
 */
export type ProductEmptyStateTextByMode = {
    'needs-setup': ProductEmptyStateText
} & {
    [Mode in Exclude<ProductEmptyStateMode, 'needs-setup'>]?: Partial<ProductEmptyStateText>
}

export interface ProductEmptyStateWizard {
    /** Subcommand for `npx -y @posthog/wizard@latest <slug>` */
    slug: string
    /** Append `--project-id=<current team>` so the wizard pre-targets the project being viewed */
    pinProjectId?: boolean
}

export interface ProductEmptyStateAccessControl {
    resourceType: AccessControlResourceType
    minAccessLevel: AccessControlLevel
}

export interface ProductEmptyStatePrimaryAction {
    label: string
    to?: string
    onClick?: () => void
    /**
     * Permission the action requires, mirroring the gated scene's own create button.
     * Without it a viewer gets an enabled button and only finds out they can't create
     * when the form fails to save.
     */
    accessControl?: ProductEmptyStateAccessControl
    /**
     * `data-attr` on the button, defaulting to `product-empty-state-primary-action`.
     * Set it to the attr the gated scene's create button carries, so end-to-end specs
     * keep one selector across both surfaces.
     */
    dataAttr?: string
}

/**
 * A primary action keyed by mode, mirroring `text`: a mode left out has no primary
 * action at all, and its hint goes with it. Key the action when it stops making sense
 * once the product is on - a one-click "Enable X" would re-send the same opt-in while
 * the screen waits for the first event.
 */
export type ProductEmptyStatePrimaryActionByMode = Partial<
    Record<ProductEmptyStateMode, ProductEmptyStatePrimaryAction>
>

export interface ProductEmptyStateConfig {
    productKey: ProductKey
    /** Eyebrow text, sentence case, e.g. "MCP analytics" */
    productName: string
    /** Eyebrow icon, e.g. `<IconMCP />` */
    icon: JSX.Element
    /** CSS color or var reference, e.g. 'var(--color-product-llm-analytics-light)' */
    accentColor: string
    /** Dark-mode accent override; falls back to `accentColor` */
    accentColorDark?: string
    /** A `pngHoggie(...)`-wrapped hedgehog, rendered above the product name */
    hedgehog?: ComponentType<{ className?: string; style?: CSSProperties }>
    /**
     * Where the hedgehog sits: `above` (default) is a small illustration above the
     * product name; `beside` renders it large next to the text and install command,
     * for wide scene-setting illustrations.
     */
    hedgehogPlacement?: 'above' | 'beside'
    text: ProductEmptyStateTextByMode
    /** Install-command CTA. Omit for creation-first products (use `primaryAction`) or self-hosted-only flows */
    wizard?: ProductEmptyStateWizard
    /**
     * Primary CTA for products set up in the UI rather than via the wizard, e.g. "Create your first flag".
     * With `wizard` also set, the terminal card stays the hero and this renders as a secondary button
     * (in place of the "Configure manually" link), for products with both a terminal and an in-app path.
     * One action covers every mode; pass a `ProductEmptyStatePrimaryActionByMode` map to vary it.
     */
    primaryAction?: ProductEmptyStatePrimaryAction | ProductEmptyStatePrimaryActionByMode
    /**
     * Rendered in the primary-action slot instead of the `primaryAction` button, for
     * actions that need hooks - e.g. a create flow that opens PostHog AI via `useMaxTool`.
     * Takes precedence over `primaryAction`.
     */
    PrimaryAction?: ComponentType
    docsUrl?: string
    /** Target of the small "Or configure manually" link; falls back to `docsUrl` */
    manualSetupUrl?: string
    /** Rendered as "<previewLabel>" with a pulsing live dot, above the preview */
    previewLabel: string
    /** Self-animating signature preview populated with realistic fake data */
    Preview: ComponentType<{ mode: ProductEmptyStateMode }>
    /** Product-specific live status line (e.g. a "listening for events" indicator), rendered under the command block */
    statusIndicator?: ReactNode
    /**
     * Whether the "Skip for now" escape hatch shows. Defaults to true. Set false for
     * creation-first products where the gated scene is just an empty list, so skipping
     * has nothing to reveal and the primary action is the only next step.
     */
    skippable?: boolean
}

/**
 * Declared on a scene's `SceneExport` to opt into the app-shell empty-state gate.
 * Both fields live in the scene's lazy chunk, so heavy assets (hedgehog PNGs,
 * preview widgets) never enter the eager graph.
 */
export interface SceneProductEmptyState {
    config: ProductEmptyStateConfig
    /**
     * The product's detection logic. The gate mounts it; it must push its
     * normalized status into `productSetupStatusLogic({ productKey })` via
     * `setDetectedStatus`.
     */
    statusLogic: LogicWrapper
    /**
     * Only gate when this feature flag is enabled. Set it when the scene itself is
     * flag-gated (so the scene's own gate keeps handling the flag-off case), or to
     * roll the empty state out gradually.
     */
    featureFlag?: FeatureFlagKey
}
