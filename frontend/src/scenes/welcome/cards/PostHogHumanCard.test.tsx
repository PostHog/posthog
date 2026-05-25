import '@testing-library/jest-dom'

import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { userLogic } from 'scenes/userLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { UserType } from '~/types'

import { WelcomePayload, welcomeDialogLogic } from '../welcomeDialogLogic'
import { PostHogHumanCard } from './PostHogHumanCard'

const INVITED_USER: UserType = {
    ...MOCK_DEFAULT_USER,
    is_organization_first_user: false,
}

const BASE_PAYLOAD: WelcomePayload = {
    organization_name: 'Acme Inc',
    inviter: null,
    team_members: [],
    recent_activity: [],
    popular_dashboards: [],
    products_in_use: [],
    suggested_next_steps: [],
    is_organization_first_user: false,
    posthog_contact: null,
    shared_slack_channel_url: null,
}

describe('PostHogHumanCard', () => {
    let logic: ReturnType<typeof welcomeDialogLogic.build>

    beforeEach(() => {
        window.localStorage.clear()
        window.sessionStorage.clear()
        useMocks({
            get: {
                '/api/organizations/@current/welcome/current/': BASE_PAYLOAD,
            },
        })
        initKeaTests()
        userLogic.mount()
        userLogic.actions.loadUserSuccess(INVITED_USER)
        logic = welcomeDialogLogic()
        logic.mount()
    }) // useMocks is the project's mock helper, not a React hook — its `use` prefix only collides naming-wise.

    function seed(overrides: Partial<WelcomePayload>): void {
        // Bypass the loader's async path so tests don't need to await network mocks just to assert
        // rendering against a deterministic payload.
        logic.actions.loadWelcomeDataSuccess({ ...BASE_PAYLOAD, ...overrides })
    }

    afterEach(() => {
        // Project jest config doesn't enable RTL auto-cleanup, so without this the previous
        // test's DOM leaks into the next and getByText fails with "multiple elements".
        cleanup()
    })

    it('renders nothing when no contact and no Slack channel is set', () => {
        seed({ posthog_contact: null, shared_slack_channel_url: null })
        const { container } = render(<PostHogHumanCard />)
        expect(container).toBeEmptyDOMElement()
    })

    it('renders the contact name when a contact is set', () => {
        seed({ posthog_contact: { name: 'Fernando' }, shared_slack_channel_url: null })
        render(<PostHogHumanCard />)
        expect(screen.getByText('Your PostHog human')).toBeInTheDocument()
        expect(screen.getByText('Fernando can help if you get stuck.')).toBeInTheDocument()
        expect(screen.queryByText('Join your shared Slack channel')).not.toBeInTheDocument()
    })

    it('renders the Slack CTA with no name when only a Slack channel is set', () => {
        seed({ posthog_contact: null, shared_slack_channel_url: 'https://posthog.slack.com/c/acme' })
        render(<PostHogHumanCard />)
        expect(screen.getByText('Your PostHog human')).toBeInTheDocument()
        const slackLink = screen.getByText('Join your shared Slack channel').closest('a')
        expect(slackLink).toHaveAttribute('href', 'https://posthog.slack.com/c/acme')
        expect(slackLink).toHaveAttribute('target', '_blank')
        // No body line when there's no name to attach it to.
        expect(screen.queryByText(/can help if you get stuck\./)).not.toBeInTheDocument()
    })

    it('tracks Slack CTA clicks via the existing welcome analytics pattern', () => {
        seed({
            posthog_contact: { name: 'Fernando' },
            shared_slack_channel_url: 'https://posthog.slack.com/c/acme',
        })
        const trackSpy = jest.spyOn(logic.actions, 'trackCardClick')
        render(<PostHogHumanCard />)
        fireEvent.click(screen.getByText('Join your shared Slack channel'))
        expect(trackSpy).toHaveBeenCalledWith('contact', 'https://posthog.slack.com/c/acme')
    })
})
