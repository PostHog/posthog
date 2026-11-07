import { MOCK_ORGANIZATION_ID } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'

import { preflightLogic } from 'lib/logic/preflightLogic'

import { initKeaTests } from '~/test/init'
import { PreflightStatus, Region } from '~/types'

import { AwsWarehouseSourcesSetupModal } from '../aws-warehouse-sources/AwsWarehouseSourcesSetupModal'
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

    type SetupModal = typeof AwsS3SetupModal | typeof AwsWarehouseSourcesSetupModal

    it.each<[string, SetupModal, Region | null, string]>([
        [
            'batch exports on US cloud',
            AwsS3SetupModal,
            Region.US,
            'arn:aws:iam::309986977637:role/posthog-external-batch-exports',
        ],
        [
            'batch exports on EU cloud',
            AwsS3SetupModal,
            Region.EU,
            'arn:aws:iam::623789312881:role/posthog-external-batch-exports',
        ],
        ['batch exports on dev', AwsS3SetupModal, Region.DEV, 'Check with your instance administrator'],
        ['batch exports on self-hosted', AwsS3SetupModal, null, 'Check with your instance administrator'],
        [
            'warehouse sources on US cloud',
            AwsWarehouseSourcesSetupModal,
            Region.US,
            'arn:aws:iam::309986977637:role/posthog-external-warehouse-sources',
        ],
        [
            'warehouse sources on EU cloud',
            AwsWarehouseSourcesSetupModal,
            Region.EU,
            'arn:aws:iam::623789312881:role/posthog-external-warehouse-sources',
        ],
        [
            'warehouse sources on self-hosted',
            AwsWarehouseSourcesSetupModal,
            null,
            'Check with your instance administrator',
        ],
    ])('shows the right role to trust for %s', (_label, SetupModal, region, expectedText) => {
        setRegion(region)
        render(
            <Provider>
                <SetupModal isOpen onComplete={jest.fn()} />
            </Provider>
        )

        expect(screen.getByText(expectedText, { exact: false })).toBeInTheDocument()
    })

    it.each<[string, SetupModal, RegExp, RegExp]>([
        ['batch exports', AwsS3SetupModal, /s3:PutObject/, /read permissions listed in the source/],
        ['warehouse sources', AwsWarehouseSourcesSetupModal, /read permissions listed in the source/, /s3:PutObject/],
    ])('asks for the permissions %s need', (_label, SetupModal, expected, unexpected) => {
        render(
            <Provider>
                <SetupModal isOpen onComplete={jest.fn()} />
            </Provider>
        )

        expect(screen.getByText(expected)).toBeInTheDocument()
        expect(screen.queryByText(unexpected)).not.toBeInTheDocument()
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
