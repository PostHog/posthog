import { cleanup, render, screen } from '@testing-library/react'

import { useMocks } from '~/mocks/jest'
import { ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel, AccessControlResourceType, AppContext } from '~/types'

import { ProductEmptyState } from './ProductEmptyState'
import type { ProductEmptyStateConfig } from './types'

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
})
