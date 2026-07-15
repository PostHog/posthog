import { MOCK_ORGANIZATION_ID } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'

import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { initKeaTests } from '~/test/init'
import { PreflightStatus, Region } from '~/types'

import { AwsS3SetupModal } from './AwsS3SetupModal'

describe('AwsS3SetupModal', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    const setRegion = (region: Region | null): void => {
        preflightLogic.mount()
        preflightLogic.actions.loadPreflightSuccess({ region } as PreflightStatus)
    }

    it('opens on the role tab with the trust policy requirements, including the external ID', async () => {
        render(
            <Provider>
                <AwsS3SetupModal isOpen onComplete={jest.fn()} />
            </Provider>
        )

        expect(screen.getByText('IAM role ARN')).toBeInTheDocument()
        expect(screen.getByText('Requirements')).toBeInTheDocument()
        expect(screen.queryByText('AWS Access Key ID')).not.toBeInTheDocument()
        // The external ID users must set in their trust policy is posthog-{organization ID}
        await waitFor(() => {
            expect(screen.getByText(`posthog-${MOCK_ORGANIZATION_ID}`)).toBeInTheDocument()
        })
    })

    it.each<[string, Region | null, string]>([
        ['US cloud', Region.US, 'arn:aws:iam::309986977637:role/posthog-external-batch-exports'],
        ['EU cloud', Region.EU, 'arn:aws:iam::623789312881:role/posthog-external-batch-exports'],
        ['dev', Region.DEV, 'Check with your instance administrator'],
        ['self-hosted', null, 'Check with your instance administrator'],
    ])('shows the right role to trust on %s', (_label, region, expectedText) => {
        setRegion(region)
        render(
            <Provider>
                <AwsS3SetupModal isOpen onComplete={jest.fn()} />
            </Provider>
        )

        expect(screen.getByText(expectedText, { exact: false })).toBeInTheDocument()
    })

    it('shows credential fields and the long-lived credentials warning on the access keys tab', async () => {
        render(
            <Provider>
                <AwsS3SetupModal isOpen onComplete={jest.fn()} />
            </Provider>
        )

        await userEvent.click(screen.getByText('Access keys'))

        expect(screen.getByText('AWS Access Key ID')).toBeInTheDocument()
        expect(screen.getByText('AWS Secret Access Key')).toBeInTheDocument()
        expect(screen.getByText(/long-lived credentials/)).toBeInTheDocument()
        expect(screen.queryByText('IAM role ARN')).not.toBeInTheDocument()
    })
})
