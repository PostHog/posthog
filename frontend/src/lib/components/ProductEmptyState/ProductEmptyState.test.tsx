import { cleanup, render, screen } from '@testing-library/react'
import { expectLogic } from 'kea-test-utils'

import { pngHoggie } from 'lib/brand/hoggies'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { useMocks } from '~/mocks/jest'
import { ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel, AccessControlResourceType, AppContext } from '~/types'

import { ProductEmptyState } from './ProductEmptyState'
import type { ProductEmptyStateConfig } from './types'

const Hedgehog = pngHoggie({ src: 'hedgehog.png', aspectRatio: 1 })

const config: ProductEmptyStateConfig = {
    productKey: ProductKey.EXPERIMENTS,
    productName: 'Experiments',
    icon: <span />,
    accentColor: 'red',
    text: { 'needs-setup': { headline: 'Headline', lead: 'Lead' } },
    primaryAction: {
        label: 'Create your first experiment',
        to: '/experiments/new',
        accessControl: {
            resourceType: AccessControlResourceType.Experiment,
            minAccessLevel: AccessControlLevel.Editor,
        },
        dataAttr: 'create-experiment',
    },
    previewLabel: 'Preview',
    Preview: () => <div />,
}

describe('ProductEmptyState', () => {
    let priorAppContext: AppContext | undefined

    beforeEach(() => {
        // preflightLogic and teamLogic mount with the component; leaving their requests
        // unanswered lets them settle after teardown and tear jsdom down mid-render.
        useMocks({
            get: {
                '/_preflight/': { cloud: false },
                '/api/environments/@current/': {},
                '/api/users/@me/': {},
            },
        })
        initKeaTests()
        priorAppContext = window.POSTHOG_APP_CONTEXT
    })

    afterEach(() => {
        cleanup()
        window.POSTHOG_APP_CONTEXT = priorAppContext
    })

    // The empty state replaces the scene's own gated create button, so a viewer who
    // reaches it must not get an enabled create action that only fails on save.
    it.each([
        [AccessControlLevel.Editor, 'false'],
        [AccessControlLevel.Viewer, 'true'],
    ])('renders the primary action for a %s as aria-disabled=%s', (userLevel, expected) => {
        window.POSTHOG_APP_CONTEXT = {
            ...window.POSTHOG_APP_CONTEXT,
            resource_access_control: {
                ...window.POSTHOG_APP_CONTEXT?.resource_access_control,
                [AccessControlResourceType.Experiment]: userLevel,
            },
        } as AppContext

        render(<ProductEmptyState config={config} mode="needs-setup" />)

        expect(screen.getByTestId('create-experiment').getAttribute('aria-disabled')).toBe(expected)
    })

    // A one-click opt-in ("Enable X") must not survive into `waiting-for-data`, where the
    // product is already on and clicking would re-send the same team update.
    it.each([
        ['needs-setup' as const, true],
        ['waiting-for-data' as const, false],
    ])('in %s renders a needs-setup-only action: %s', (mode, expected) => {
        const modeKeyedConfig: ProductEmptyStateConfig = {
            ...config,
            text: {
                'needs-setup': { headline: 'Headline', lead: 'Lead', hint: 'Hint' },
                'waiting-for-data': { headline: 'Waiting' },
            },
            primaryAction: { 'needs-setup': { label: 'Enable experiments', dataAttr: 'enable-experiments' } },
        }

        render(<ProductEmptyState config={modeKeyedConfig} mode={mode} />)

        expect(!!screen.queryByTestId('enable-experiments')).toBe(expected)
        // The hint introduces the action, so it leaves with it rather than dangling.
        expect(!!screen.queryByText('Hint')).toBe(expected)
    })

    // An install command keyed to `needs-setup` must not survive into `waiting-for-data`:
    // events already flow, so there is nothing left to install.
    it.each([
        ['needs-setup' as const, true],
        ['waiting-for-data' as const, false],
    ])('in %s renders a needs-setup-only wizard: %s', async (mode, expected) => {
        // preflightLogic is already mounted with cloud off; the wizard card only renders on cloud.
        useMocks({ get: { '/_preflight/': { cloud: true } } })
        preflightLogic.actions.loadPreflight()
        await expectLogic(preflightLogic).toDispatchActions(['loadPreflightSuccess'])
        const modeKeyedConfig: ProductEmptyStateConfig = {
            ...config,
            primaryAction: undefined,
            text: {
                'needs-setup': { headline: 'Headline', lead: 'Lead', hint: 'Hint' },
                'waiting-for-data': { headline: 'Waiting' },
            },
            wizard: { 'needs-setup': { slug: 'experiments' } },
        }

        render(<ProductEmptyState config={modeKeyedConfig} mode={mode} />)

        if (expected) {
            expect(await screen.findByLabelText(/Copy command/)).toBeTruthy()
        } else {
            expect(screen.queryByLabelText(/Copy command/)).toBeNull()
        }
        expect(!!screen.queryByText('Hint')).toBe(expected)
    })

    // Overrides keyed by a flag let a config roll out a new call to action without a second
    // config: they must apply only while the flag is on, `primaryAction: undefined` must drop
    // the action, and a text field left out of the override must keep its base value.
    it.each([
        [false, false],
        [true, true],
    ])('with its flag on=%s applies the feature flag overrides: %s', async (flagOn, applied) => {
        useMocks({ get: { '/_preflight/': { cloud: true } } })
        preflightLogic.actions.loadPreflight()
        await expectLogic(preflightLogic).toDispatchActions(['loadPreflightSuccess'])
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([], flagOn ? { [FEATURE_FLAGS.ERROR_TRACKING_NEW_WIZARD]: true } : {})
        const overriddenConfig: ProductEmptyStateConfig = {
            ...config,
            text: { 'needs-setup': { headline: 'Headline', lead: 'Lead', hint: 'Base hint' } },
            featureFlagOverrides: {
                [FEATURE_FLAGS.ERROR_TRACKING_NEW_WIZARD]: {
                    text: { 'needs-setup': { hint: 'Override hint' } },
                    wizard: { slug: 'experiments' },
                    primaryAction: undefined,
                },
            },
        }

        render(<ProductEmptyState config={overriddenConfig} mode="needs-setup" />)

        if (applied) {
            expect(await screen.findByLabelText(/Copy command/)).toBeTruthy()
        } else {
            expect(screen.queryByLabelText(/Copy command/)).toBeNull()
        }
        expect(!!screen.queryByTestId('create-experiment')).toBe(!applied)
        expect(!!screen.queryByText('Override hint')).toBe(applied)
        expect(!!screen.queryByText('Base hint')).toBe(!applied)
        expect(screen.getByText('Headline')).toBeTruthy()
    })

    // `beside` renders a pair and a container query hides one of them at any width. A lazy
    // image with no layout box has nothing to intersect, so the browser can leave it unfetched
    // until a resize reveals it. The Storybook image gate skips hidden images.
    it.each([
        ['above' as const, ['lazy']],
        ['beside' as const, ['eager', 'eager']],
    ])('renders a %s hedgehog loading as %s', (hedgehogPlacement, expected) => {
        const { container } = render(
            <ProductEmptyState config={{ ...config, hedgehog: Hedgehog, hedgehogPlacement }} mode="needs-setup" />
        )

        const loading = Array.from(container.querySelectorAll('img[src="hedgehog.png"]')).map((image) =>
            image.getAttribute('loading')
        )
        expect(loading).toEqual(expected)
    })
})
