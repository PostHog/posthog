import { useActions, useValues } from 'kea'

import {
    LemonBanner,
    LemonButton,
    LemonCheckbox,
    LemonInput,
    LemonSegmentedButton,
    LemonSelect,
    LemonSwitch,
    LemonTextArea,
} from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { upgradeModalLogic } from 'lib/components/UpgradeModal/upgradeModalLogic'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel'
import { apiHostOrigin } from 'lib/utils/apiHost'
import { SceneExport } from 'scenes/sceneTypes'
import { ColorInput } from 'scenes/surveys/wizard/ColorInput'
import { teamLogic } from 'scenes/teamLogic'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'
import { AvailableFeature } from '~/types'

import { COOKIE_BANNER_ART } from './art'
import {
    ART_STYLE_LABELS,
    LANGUAGE_OPTIONS,
    MAX_CATEGORIES,
    POSITION_LABELS,
    THEME_PALETTES,
    ThemePreset,
} from './constants'
import { cookieBannerLogic } from './cookieBannerLogic'
import { CookieBannerPreview } from './CookieBannerPreview'
import type { CookieBannerAppearanceApi, CookieBannerTranslationApi } from './generated/api.schemas'
import {
    cookieBannerCreateBodyAppearanceOneAcceptButtonTextMax,
    cookieBannerCreateBodyAppearanceOneDeclineButtonTextMax,
    cookieBannerCreateBodyAppearanceOneDescriptionMax,
    cookieBannerCreateBodyAppearanceOnePreferencesButtonTextMax,
    cookieBannerCreateBodyAppearanceOneTitleMax,
} from './generated/api.zod'

export const scene: SceneExport = {
    component: CookieBannerScene,
    logic: cookieBannerLogic,
    productKey: ProductKey.COOKIE_BANNER,
}

const TEXT_FIELDS: { key: keyof CookieBannerAppearanceApi; label: string; maxLength: number; textarea?: boolean }[] = [
    { key: 'title', label: 'Title', maxLength: cookieBannerCreateBodyAppearanceOneTitleMax },
    {
        key: 'description',
        label: 'Description',
        maxLength: cookieBannerCreateBodyAppearanceOneDescriptionMax,
        textarea: true,
    },
    {
        key: 'acceptButtonText',
        label: 'Accept button',
        maxLength: cookieBannerCreateBodyAppearanceOneAcceptButtonTextMax,
    },
    {
        key: 'declineButtonText',
        label: 'Decline button',
        maxLength: cookieBannerCreateBodyAppearanceOneDeclineButtonTextMax,
    },
]

const COLOR_FIELDS: { key: keyof CookieBannerAppearanceApi; label: string }[] = [
    { key: 'backgroundColor', label: 'Background' },
    { key: 'textColor', label: 'Text' },
    { key: 'buttonColor', label: 'Accept button' },
    { key: 'buttonTextColor', label: 'Accept button text' },
]

const TRANSLATABLE_FIELDS: { key: keyof CookieBannerTranslationApi; label: string; maxLength: number }[] = [
    { key: 'title', label: 'Title', maxLength: cookieBannerCreateBodyAppearanceOneTitleMax },
    { key: 'description', label: 'Description', maxLength: cookieBannerCreateBodyAppearanceOneDescriptionMax },
    {
        key: 'acceptButtonText',
        label: 'Accept button',
        maxLength: cookieBannerCreateBodyAppearanceOneAcceptButtonTextMax,
    },
    {
        key: 'declineButtonText',
        label: 'Decline button',
        maxLength: cookieBannerCreateBodyAppearanceOneDeclineButtonTextMax,
    },
    {
        key: 'preferencesButtonText',
        label: 'Preferences link',
        maxLength: cookieBannerCreateBodyAppearanceOnePreferencesButtonTextMax,
    },
]

function languageLabel(code: string): string {
    return LANGUAGE_OPTIONS.find((option) => option.value === code)?.label ?? code
}

export function CookieBannerScene(): JSX.Element {
    const {
        activeTheme,
        appearanceDraft,
        configLoading,
        enabledDraft,
        effectiveAppearance,
        isDirty,
        showLightArtWarning,
        translationLanguages,
    } = useValues(cookieBannerLogic)
    const {
        setEnabled,
        setAppearanceValue,
        setAppearanceValues,
        addTranslationLanguage,
        removeTranslationLanguage,
        setTranslationValue,
        addCategory,
        removeCategory,
        setCategoryValue,
        save,
    } = useActions(cookieBannerLogic)
    const { guardAvailableFeature } = useValues(upgradeModalLogic)
    const { currentTeam } = useValues(teamLogic)

    return (
        <SceneContent>
            <SceneTitleSection
                name="Cookie banner"
                description="Show a cookie consent banner that gates PostHog and your other scripts on the visitor's choice."
                resourceType={{ type: 'cookie_banner' }}
                actions={
                    <LemonButton
                        type="primary"
                        onClick={() => save()}
                        loading={configLoading}
                        disabledReason={configLoading ? 'Loading…' : !isDirty ? 'No changes to save' : undefined}
                        data-attr="cookie-banner-save"
                    >
                        Save
                    </LemonButton>
                }
            />
            <SceneDivider />
            <LemonBanner type="info">
                Using this banner doesn't make your site compliant on its own. Consent requirements depend on your
                jurisdiction and what your site does, so review your setup with your own legal counsel. PostHog doesn't
                provide legal advice.
            </LemonBanner>
            <div className="flex flex-col lg:flex-row gap-8">
                <div className="flex flex-col gap-8 lg:max-w-160 flex-1">
                    <SceneSection
                        title="Status"
                        description="Applies immediately. The banner is only served to your website while enabled."
                        titleSize="sm"
                    >
                        <LemonSwitch
                            label="Enable cookie banner"
                            checked={enabledDraft}
                            onChange={setEnabled}
                            disabled={configLoading}
                            bordered
                        />
                    </SceneSection>
                    <div className="flex flex-col gap-4">
                        {TEXT_FIELDS.map(({ key, label, maxLength, textarea }) => (
                            <div key={key}>
                                <LemonLabel className="mb-1">{label}</LemonLabel>
                                {textarea ? (
                                    <LemonTextArea
                                        value={String(effectiveAppearance[key])}
                                        onChange={(value) => setAppearanceValue(key, value)}
                                        maxLength={maxLength}
                                        data-attr={`cookie-banner-${key}`}
                                    />
                                ) : (
                                    <LemonInput
                                        value={String(effectiveAppearance[key])}
                                        onChange={(value) => setAppearanceValue(key, value)}
                                        maxLength={maxLength}
                                        data-attr={`cookie-banner-${key}`}
                                    />
                                )}
                            </div>
                        ))}
                    </div>
                    <div className="flex flex-col gap-4">
                        <div>
                            <LemonLabel className="mb-1">Theme</LemonLabel>
                            <LemonSegmentedButton
                                value={activeTheme ?? undefined}
                                onChange={(theme) => setAppearanceValues(THEME_PALETTES[theme as ThemePreset])}
                                options={[
                                    { value: 'light', label: 'Light' },
                                    { value: 'dark', label: 'Dark' },
                                ]}
                                data-attr="cookie-banner-theme"
                            />
                        </div>
                        <div>
                            <LemonLabel className="mb-1">Art</LemonLabel>
                            <div className="flex gap-2 flex-wrap">
                                {(Object.keys(ART_STYLE_LABELS) as (keyof typeof ART_STYLE_LABELS)[]).map((style) => (
                                    <LemonButton
                                        key={style}
                                        type="secondary"
                                        active={effectiveAppearance.artStyle === style}
                                        onClick={() => setAppearanceValue('artStyle', style)}
                                        data-attr={`cookie-banner-art-${style}`}
                                    >
                                        <span className="flex flex-col items-center gap-1 py-1">
                                            {COOKIE_BANNER_ART[style] ? (
                                                <span
                                                    className={
                                                        // The light logomark is white art — give its tile a dark
                                                        // backing so it's visible in the picker
                                                        style === 'posthog-logomark-light'
                                                            ? 'flex h-12 items-center rounded bg-[#1d1f27] px-2'
                                                            : 'flex h-12 items-center'
                                                    }
                                                    // Static app-owned SVG markup, never user input
                                                    dangerouslySetInnerHTML={{
                                                        __html: COOKIE_BANNER_ART[style],
                                                    }}
                                                />
                                            ) : (
                                                <span className="flex h-12 items-center text-muted">None</span>
                                            )}
                                            <span className="text-xs font-normal">{ART_STYLE_LABELS[style]}</span>
                                        </span>
                                    </LemonButton>
                                ))}
                            </div>
                            {showLightArtWarning && (
                                <LemonBanner type="warning" className="mt-2">
                                    The light logomark is designed for dark backgrounds. It may be invisible on your
                                    current background color. Switch to the dark theme or pick a darker background.
                                </LemonBanner>
                            )}
                        </div>
                        <div>
                            <LemonLabel className="mb-1">Position</LemonLabel>
                            <LemonSegmentedButton
                                value={effectiveAppearance.position}
                                onChange={(value) => setAppearanceValue('position', value)}
                                options={(Object.keys(POSITION_LABELS) as (keyof typeof POSITION_LABELS)[]).map(
                                    (position) => ({ value: position, label: POSITION_LABELS[position] })
                                )}
                                data-attr="cookie-banner-position"
                            />
                        </div>
                        <div className="grid grid-cols-2 gap-3">
                            {COLOR_FIELDS.map(({ key, label }) => (
                                <div key={key}>
                                    <LemonLabel className="mb-1">{label}</LemonLabel>
                                    <ColorInput
                                        value={String(effectiveAppearance[key])}
                                        onChange={(value) => setAppearanceValue(key, value)}
                                    />
                                </div>
                            ))}
                        </div>
                    </div>
                    <SceneSection
                        title="Consent options"
                        description="How the banner handles the visitor's choice."
                        titleSize="sm"
                    >
                        <div className="flex flex-col gap-3">
                            <LemonCheckbox
                                label="Let visitors manage preferences"
                                checked={effectiveAppearance.showPreferences}
                                onChange={(checked) => setAppearanceValue('showPreferences', checked)}
                                data-attr="cookie-banner-show-preferences"
                            />
                            <p className="text-muted text-xs m-0 -mt-2">
                                Adds a link that opens a panel where visitors grant or deny each consent category
                                separately.
                            </p>
                            {effectiveAppearance.showPreferences && (
                                <div className="max-w-80">
                                    <LemonLabel className="mb-1">Preferences link text</LemonLabel>
                                    <LemonInput
                                        value={String(effectiveAppearance.preferencesButtonText)}
                                        onChange={(value) => setAppearanceValue('preferencesButtonText', value)}
                                        maxLength={cookieBannerCreateBodyAppearanceOnePreferencesButtonTextMax}
                                        data-attr="cookie-banner-preferencesButtonText"
                                    />
                                </div>
                            )}
                            <LemonCheckbox
                                label="Cookieless fallback on decline"
                                checked={effectiveAppearance.cookielessFallback}
                                onChange={(checked) => setAppearanceValue('cookielessFallback', checked)}
                                data-attr="cookie-banner-cookieless-fallback"
                            />
                            <p className="text-muted text-xs m-0 -mt-2">
                                When a visitor declines, keep anonymous analytics with in-memory persistence: nothing is
                                stored on their device and each page load starts a fresh anonymous session.
                            </p>
                            <LemonCheckbox
                                label="Respect Global Privacy Control"
                                checked={effectiveAppearance.respectGpc}
                                onChange={(checked) => setAppearanceValue('respectGpc', checked)}
                                data-attr="cookie-banner-respect-gpc"
                            />
                            <p className="text-muted text-xs m-0 -mt-2">
                                Visitors whose browser broadcasts the GPC signal are treated as declined and never shown
                                the banner. An explicit choice made on your site still takes precedence.
                            </p>
                            <LemonCheckbox
                                label="Google Consent Mode v2"
                                checked={effectiveAppearance.googleConsentMode}
                                onChange={(checked) => setAppearanceValue('googleConsentMode', checked)}
                                data-attr="cookie-banner-google-consent-mode"
                            />
                            <p className="text-muted text-xs m-0 -mt-2">
                                Pushes a denied consent default before your Google tags run, then an update on the
                                visitor's choice. Analytics maps to <code>analytics_storage</code>; marketing maps to
                                the ad signals.
                            </p>
                        </div>
                    </SceneSection>
                    <SceneSection
                        title="Consent categories"
                        description="What visitors can grant or deny. Use a category's key in data-ph-consent script attributes to gate your own scripts."
                        titleSize="sm"
                    >
                        <div className="flex flex-col gap-2">
                            <div className="rounded border p-3 flex items-center justify-between">
                                <div>
                                    <LemonLabel>Necessary</LemonLabel>
                                    <p className="text-muted text-xs m-0">
                                        Always on. Shown in the preferences panel but can't be declined.
                                    </p>
                                </div>
                            </div>
                            {effectiveAppearance.categories.map((category, index) => {
                                const isAnalytics = category.key === 'analytics'
                                return (
                                    <div key={index} className="rounded border p-3 flex flex-col gap-2">
                                        <div className="flex gap-2">
                                            <div className="flex-1">
                                                <LemonLabel className="mb-1">Key</LemonLabel>
                                                <LemonInput
                                                    value={category.key}
                                                    onChange={(value) => setCategoryValue(index, 'key', value)}
                                                    disabled={isAnalytics}
                                                    placeholder="e.g. marketing"
                                                    data-attr="cookie-banner-category-key"
                                                />
                                            </div>
                                            <div className="flex-1">
                                                <LemonLabel className="mb-1">Label</LemonLabel>
                                                <LemonInput
                                                    value={category.label}
                                                    onChange={(value) => setCategoryValue(index, 'label', value)}
                                                    placeholder="Shown to visitors"
                                                    data-attr="cookie-banner-category-label"
                                                />
                                            </div>
                                            <div className="flex items-end">
                                                <LemonButton
                                                    size="small"
                                                    status="danger"
                                                    onClick={() => removeCategory(index)}
                                                    disabledReason={
                                                        isAnalytics
                                                            ? 'Analytics drives PostHog tracking consent and is required'
                                                            : undefined
                                                    }
                                                    data-attr="cookie-banner-category-remove"
                                                >
                                                    Remove
                                                </LemonButton>
                                            </div>
                                        </div>
                                        <div>
                                            <LemonLabel className="mb-1">Description (optional)</LemonLabel>
                                            <LemonInput
                                                value={category.description ?? ''}
                                                onChange={(value) => setCategoryValue(index, 'description', value)}
                                                placeholder="One line shown under the category"
                                                data-attr="cookie-banner-category-description"
                                            />
                                        </div>
                                        {isAnalytics && (
                                            <p className="text-muted text-xs m-0">
                                                Controls PostHog tracking. Required.
                                            </p>
                                        )}
                                    </div>
                                )
                            })}
                            <div>
                                <LemonButton
                                    type="secondary"
                                    onClick={() => addCategory()}
                                    disabledReason={
                                        effectiveAppearance.categories.length >= MAX_CATEGORIES
                                            ? `At most ${MAX_CATEGORIES} categories`
                                            : undefined
                                    }
                                    data-attr="cookie-banner-category-add"
                                >
                                    Add category
                                </LemonButton>
                            </div>
                        </div>
                    </SceneSection>
                    <SceneSection
                        title="Languages"
                        description="Serve translated copy based on the visitor's browser language. Visitors without a matching language see the default copy."
                        titleSize="sm"
                    >
                        <div className="flex flex-col gap-4">
                            {translationLanguages.map((language: string) => (
                                <div key={language} className="rounded border p-3 flex flex-col gap-2">
                                    <div className="flex items-center justify-between">
                                        <LemonLabel>
                                            {languageLabel(language)}{' '}
                                            <span className="text-muted font-normal">({language})</span>
                                        </LemonLabel>
                                        <LemonButton
                                            size="small"
                                            status="danger"
                                            onClick={() => removeTranslationLanguage(language)}
                                            data-attr="cookie-banner-remove-language"
                                        >
                                            Remove
                                        </LemonButton>
                                    </div>
                                    {TRANSLATABLE_FIELDS.filter(
                                        ({ key }) =>
                                            key !== 'preferencesButtonText' || effectiveAppearance.showPreferences
                                    ).map(({ key, label, maxLength }) => (
                                        <div key={key}>
                                            <LemonLabel className="mb-1">{label}</LemonLabel>
                                            <LemonInput
                                                value={appearanceDraft.translations?.[language]?.[key] ?? ''}
                                                onChange={(value) => setTranslationValue(language, key, value)}
                                                placeholder={String(effectiveAppearance[key])}
                                                maxLength={maxLength}
                                                data-attr={`cookie-banner-translation-${key}`}
                                            />
                                        </div>
                                    ))}
                                </div>
                            ))}
                            <div className="max-w-80">
                                <LemonSelect
                                    placeholder="Add language"
                                    value={null}
                                    onChange={(language) => language && addTranslationLanguage(language)}
                                    options={LANGUAGE_OPTIONS.filter(
                                        (option) => !translationLanguages.includes(option.value)
                                    )}
                                    data-attr="cookie-banner-add-language"
                                />
                            </div>
                        </div>
                    </SceneSection>
                    <SceneSection
                        title="Branding"
                        description="Removing the notice requires the white labelling entitlement on your plan."
                        titleSize="sm"
                    >
                        <LemonCheckbox
                            label="Hide PostHog branding"
                            checked={effectiveAppearance.whiteLabel}
                            onChange={(checked) => {
                                if (checked) {
                                    guardAvailableFeature(AvailableFeature.WHITE_LABELLING, () =>
                                        setAppearanceValue('whiteLabel', true)
                                    )
                                } else {
                                    setAppearanceValue('whiteLabel', false)
                                }
                            }}
                            data-attr="cookie-banner-white-label"
                        />
                    </SceneSection>
                </div>
                <div className="flex-1 min-w-0">
                    <SceneSection
                        title="Preview"
                        description="A live preview of the banner as your visitors will see it."
                        titleSize="sm"
                    >
                        <CookieBannerPreview appearance={effectiveAppearance} />
                    </SceneSection>
                </div>
            </div>
            <SceneDivider />
            <SceneSection
                title="Installation"
                description="The consent script must be the first script tag on the page: before the PostHog snippet and before any script it should gate."
                titleSize="sm"
            >
                <div className="flex flex-col gap-2 max-w-240">
                    <p className="m-0">1. Add the consent script at the very top of your page's head:</p>
                    <CodeSnippet language={Language.HTML}>
                        {`<script src="${apiHostOrigin()}/array/${currentTeam?.api_token ?? '<your project API key>'}/cookie-banner.js"></script>`}
                    </CodeSnippet>
                    <p className="m-0">
                        2. Keep your PostHog snippet below it, with these init options so nothing is captured or stored
                        before the visitor chooses:
                    </p>
                    <CodeSnippet language={Language.JavaScript}>
                        {`posthog.init('${currentTeam?.api_token ?? '<your project API key>'}', {
    api_host: '${apiHostOrigin()}',
    opt_out_capturing_by_default: true, // no events before consent
    opt_out_persistence_by_default: true, // no cookies before consent
})`}
                    </CodeSnippet>
                    <p className="m-0">
                        3. To block your other scripts until consent, change their type to <code>text/plain</code> and
                        add a <code>data-ph-consent</code> attribute with a category key. They run as soon as the
                        visitor grants that category:
                    </p>
                    <CodeSnippet language={Language.HTML}>
                        {`<script type="text/plain" data-ph-consent="marketing" src="https://example.com/ad-pixel.js"></script>`}
                    </CodeSnippet>
                    <p className="m-0">
                        You can also listen for the <code>posthog:consent</code> event. It fires when a choice is made
                        and again on every page load once one is stored:
                    </p>
                    <CodeSnippet language={Language.JavaScript}>
                        {`window.addEventListener('posthog:consent', (event) => {
    // event.detail: { status: 'accepted' | 'declined', source: 'user' | 'stored' | 'gpc',
    //                 categories: { analytics: boolean, marketing: boolean, ... } }
    if (event.detail.categories.marketing) {
        // load your marketing scripts here
    }
})`}
                    </CodeSnippet>
                </div>
            </SceneSection>
        </SceneContent>
    )
}

export default CookieBannerScene
