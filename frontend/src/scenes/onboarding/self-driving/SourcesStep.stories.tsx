import type { Meta, StoryObj } from '@storybook/react'
import { type ReactNode } from 'react'

import { mswDecorator } from '~/mocks/browser'
import preflightJson from '~/mocks/fixtures/_preflight.json'

import { SourcesStepInner } from './ContextOnboarding'

/**
 * The "Turn on your sources" step in isolation. Rendered as the presentational sub-component
 * (SourcesStepInner) with `installing` driven by an arg — mirrors the ContextWarehouseStep pattern, so
 * the in-flight state is exercised without standing up the cloud-run TaskRun stream (no EventSource).
 *
 * Source active/off state comes from the default mock team (autocapture is on by default, so Product
 * analytics renders active); the badge each card shows then depends on `installing` and the SDK.
 */

// Wrap the step in a card that mirrors the real onboarding surface (the sources step is the wide variant).
function OnboardingCard({ children }: { children: ReactNode }): JSX.Element {
    return (
        <div className="min-h-screen bg-primary p-8">
            <div className="max-w-3xl mx-auto bg-surface-primary border border-primary rounded-xl p-8">
                <h1 className="text-2xl font-bold text-center mb-5">Turn on your sources</h1>
                {children}
            </div>
        </div>
    )
}

const meta: Meta<typeof SourcesStepInner> = {
    title: 'Scenes-Other/Onboarding/Turn on your sources',
    component: SourcesStepInner,
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-05-25',
    },
    decorators: [
        (Story) => (
            <OnboardingCard>
                <Story />
            </OnboardingCard>
        ),
        mswDecorator({
            get: {
                '/_preflight': { ...preflightJson, cloud: true, realm: 'cloud' },
                '/stats': {},
                '/events': {},
            },
        }),
    ],
}
export default meta

type Story = StoryObj<typeof SourcesStepInner>

const CONNECTED_CODEBASE = { connected: true, displayName: 'acme-co', connectUrl: '#' }

/** Default: each card shows its config status — "Active" once events flow, "Needs install" when turned
 * on with nothing installed, "Off" when disabled. Codebase access is connected, so it reads "Active". */
export const Default: Story = { args: { installing: false, repository: null, codebase: CONNECTED_CODEBASE } }

/** While an install is in flight (into the named repo), turned-on sources read "Installing" and
 * turned-off ones read "Available" — turn any on and it gets installed too. */
export const Installing: Story = {
    args: { installing: true, repository: 'acme-co/web', codebase: CONNECTED_CODEBASE },
    // The install-in-progress spinner is the point of this story — it never resolves, so skip
    // the test runner's default "wait for loaders to hide" check.
    parameters: { testOptions: { waitForLoadersToDisappear: false } },
}

/** GitHub not connected — the codebase-access card offers a "Connect GitHub" button to activate it as a
 * source, independent of the SDK install. */
export const CodebaseNotConnected: Story = {
    args: { installing: false, repository: null, codebase: { connected: false, displayName: null, connectUrl: '#' } },
}
