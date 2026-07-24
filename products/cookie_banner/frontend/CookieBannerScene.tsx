import { useActions, useValues } from 'kea'

import {
    LemonButton,
    LemonCheckbox,
    LemonDivider,
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
import { teamLogic } from 'scenes/teamLogic'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'
import { AvailableFeature } from '~/types'

import { COOKIE_BANNER_ART } from './art'
import { ART_STYLE_LABELS, POSITION_LABELS } from './constants'
import { cookieBannerLogic } from './cookieBannerLogic'
import { CookieBannerPreview } from './CookieBannerPreview'
import type { CookieBannerAppearanceApi } from './generated/api.schemas'

export const scene: SceneExport = {
    component: CookieBannerScene,
    logic: cookieBannerLogic,
    productKey: ProductKey.COOKIE_BANNER,
}

const TEXT_FIELDS: { key: keyof CookieBannerAppearanceApi; label: string; textarea?: boolean }[] = [
    { key: 'title', label: 'Title' },
    { key: 'description', label: 'Description', textarea: true },
    { key: 'acceptButtonText', label: 'Accept button' },
    { key: 'declineButtonText', label: 'Decline button' },
]

const COLOR_FIELDS: { key: keyof CookieBannerAppearanceApi; label: string }[] = [
    { key: 'backgroundColor', label: 'Background' },
    { key: 'textColor', label: 'Text' },
    { key: 'buttonColor', label: 'Accept button' },
    { key: 'buttonTextColor', label: 'Accept button text' },
]

export function CookieBannerScene(): JSX.Element {
    const { configLoading, enabledDraft, effectiveAppearance, isDirty, saving } = useValues(cookieBannerLogic)
    const { setEnabled, setAppearanceValue, save } = useActions(cookieBannerLogic)
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
                        loading={saving}
                        disabledReason={configLoading ? 'Loading…' : !isDirty ? 'No changes to save' : undefined}
                        data-attr="cookie-banner-save"
                    >
                        Save
                    </LemonButton>
                }
            />
            <div className="flex flex-col lg:flex-row gap-8">
                <div className="flex flex-col gap-4 lg:max-w-160 flex-1">
                    <LemonSwitch
                        label="Enable cookie banner"
                        checked={enabledDraft}
                        onChange={setEnabled}
                        disabled={configLoading}
                        bordered
                    />
                    {TEXT_FIELDS.map(({ key, label, textarea }) => (
                        <div key={key}>
                            <LemonLabel className="mb-1">{label}</LemonLabel>
                            {textarea ? (
                                <LemonTextArea
                                    value={String(effectiveAppearance[key])}
                                    onChange={(value) => setAppearanceValue(key, value)}
                                    maxLength={1000}
                                />
                            ) : (
                                <LemonInput
                                    value={String(effectiveAppearance[key])}
                                    onChange={(value) => setAppearanceValue(key, value)}
                                    maxLength={200}
                                />
                            )}
                        </div>
                    ))}
                    <div>
                        <LemonLabel className="mb-1">Art</LemonLabel>
                        <div className="flex gap-2 flex-wrap">
                            {(Object.keys(ART_STYLE_LABELS) as (keyof typeof ART_STYLE_LABELS)[]).map((style) => (
                                <LemonButton
                                    key={style}
                                    type="secondary"
                                    active={effectiveAppearance.artStyle === style}
                                    onClick={() => setAppearanceValue('artStyle', style)}
                                    tooltip={ART_STYLE_LABELS[style]}
                                    data-attr={`cookie-banner-art-${style}`}
                                >
                                    {COOKIE_BANNER_ART[style] ? (
                                        <span
                                            className="flex h-8 items-center"
                                            // Static app-owned SVG markup, never user input
                                            dangerouslySetInnerHTML={{ __html: COOKIE_BANNER_ART[style] }}
                                        />
                                    ) : (
                                        <span className="flex h-8 items-center">None</span>
                                    )}
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
                        />
                    </div>
                    <div className="grid grid-cols-2 gap-3">
                        {COLOR_FIELDS.map(({ key, label }) => (
                            <div key={key}>
                                <LemonLabel className="mb-1">{label}</LemonLabel>
                                <LemonInput
                                    value={String(effectiveAppearance[key])}
                                    onChange={(value) => setAppearanceValue(key, value)}
                                    prefix={
                                        <span
                                            className="inline-block w-4 h-4 rounded border"
                                            style={{ backgroundColor: String(effectiveAppearance[key]) }}
                                        />
                                    }
                                />
                            </div>
                        ))}
                    </div>
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
                    />
                </div>
                <div className="flex-1 min-w-0">
                    <LemonLabel className="mb-1">Preview</LemonLabel>
                    <CookieBannerPreview appearance={effectiveAppearance} />
                </div>
            </div>
            <LemonDivider />
            <div className="flex flex-col gap-2 max-w-240">
                <h3 className="m-0">Installation</h3>
                <p className="m-0">
                    The banner is delivered through your existing PostHog snippet. Two init options are needed:{' '}
                    <code>opt_in_site_apps</code> lets the banner run, and <code>opt_out_capturing_by_default</code>{' '}
                    holds off tracking until the visitor accepts.
                </p>
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
        </SceneContent>
    )
}

export default CookieBannerScene
