import { useActions, useValues } from 'kea'

import {
    LemonButton,
    LemonCheckbox,
    LemonInput,
    LemonSegmentedButton,
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
import { ART_STYLE_LABELS, POSITION_LABELS, THEME_PALETTES, ThemePreset } from './constants'
import { cookieBannerLogic } from './cookieBannerLogic'
import { CookieBannerPreview } from './CookieBannerPreview'
import type { CookieBannerAppearanceApi } from './generated/api.schemas'
import {
    cookieBannerCreateBodyAppearanceOneAcceptButtonTextMax,
    cookieBannerCreateBodyAppearanceOneDeclineButtonTextMax,
    cookieBannerCreateBodyAppearanceOneDescriptionMax,
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

export function CookieBannerScene(): JSX.Element {
    const { activeTheme, configLoading, enabledDraft, effectiveAppearance, isDirty } = useValues(cookieBannerLogic)
    const { setEnabled, setAppearanceValue, setAppearanceValues, save } = useActions(cookieBannerLogic)
    const { guardAvailableFeature } = useValues(upgradeModalLogic)
    const { currentTeam } = useValues(teamLogic)

    return (
        <SceneContent>
            <SceneTitleSection
                name="Cookie banner"
                description="Show a compliant cookie consent banner on your website. Visitors' choices are wired straight into PostHog tracking consent."
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
            <div className="flex flex-col lg:flex-row gap-8">
                <div className="flex flex-col gap-8 lg:max-w-160 flex-1">
                    <SceneSection
                        title="Status"
                        description="The banner is only served to your website while enabled."
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
                                                    className="flex h-12 items-center"
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
                description="The banner is delivered through your existing PostHog snippet. Two init options are needed."
                titleSize="sm"
            >
                <div className="flex flex-col gap-2 max-w-240">
                    <CodeSnippet language={Language.JavaScript}>
                        {`posthog.init('${currentTeam?.api_token ?? '<your project API key>'}', {
    api_host: '${apiHostOrigin()}',
    opt_in_site_apps: true, // required: allows the cookie banner to run
    opt_out_capturing_by_default: true, // recommended: no tracking before consent
})`}
                    </CodeSnippet>
                    <p className="m-0">
                        To gate your other scripts on the visitor's choice, listen for the <code>posthog:consent</code>{' '}
                        event. It fires when a choice is made and again on every page load once one is stored.
                    </p>
                    <CodeSnippet language={Language.JavaScript}>
                        {`window.addEventListener('posthog:consent', (event) => {
    if (event.detail.status === 'accepted') {
        // load your other analytics or marketing scripts here
    }
})`}
                    </CodeSnippet>
                </div>
            </SceneSection>
        </SceneContent>
    )
}

export default CookieBannerScene
