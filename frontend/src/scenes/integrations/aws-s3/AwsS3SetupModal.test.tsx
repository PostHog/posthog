import { MOCK_ORGANIZATION_ID } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'

import { initKeaTests } from '~/test/init'

import { AwsS3SetupModal } from './AwsS3SetupModal'

describe('AwsS3SetupModal', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it('opens on the role tab with the trust policy requirements, including the external ID', async () => {
        render(
            <Provider>
                <AwsS3SetupModal isOpen onComplete={jest.fn()} />
            </Provider>
        )

        expect(screen.getByText('IAM role ARN')).toBeInTheDocument()
        expect(screen.getByText('Requirements')).toBeInTheDocument()
        expect(screen.queryByText('AWS Access Key ID')).not.toBeInTheDocument()
        // The external ID users must set in their trust policy is the organization ID
        await waitFor(() => {
            expect(screen.getByText(MOCK_ORGANIZATION_ID)).toBeInTheDocument()
        })
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
