import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { Provider } from 'kea'

import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { initKeaTests } from '~/test/init'
import { PreflightStatus, Region } from '~/types'

import { AwsKinesisSetupModal } from './AwsKinesisSetupModal'

describe('AwsKinesisSetupModal', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it.each<[string, string | null, string]>([
        [
            'the role configured on the instance',
            'arn:aws:iam::123456789012:role/example-cdp-role',
            'arn:aws:iam::123456789012:role/example-cdp-role',
        ],
        ['the fallback when the instance has no role', null, 'Check with your instance administrator'],
    ])('shows %s, never the batch exports role', (_label, cdpRoleArn, expectedText) => {
        preflightLogic.mount()
        preflightLogic.actions.loadPreflightSuccess({
            region: Region.US,
            cdp_aws_external_role_arn: cdpRoleArn,
        } as PreflightStatus)

        render(
            <Provider>
                <AwsKinesisSetupModal isOpen onComplete={jest.fn()} />
            </Provider>
        )

        expect(screen.getByText(expectedText, { exact: false })).toBeInTheDocument()
        expect(screen.queryByText('posthog-external-batch-exports', { exact: false })).not.toBeInTheDocument()
    })
})
