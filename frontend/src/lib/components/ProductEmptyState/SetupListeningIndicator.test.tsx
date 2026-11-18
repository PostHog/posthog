import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { kea, path } from 'kea'

import { ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { productSetupStatusLogic } from './productSetupStatusLogic'
import { SetupListeningIndicator } from './SetupListeningIndicator'

const detectionLogic = kea([path(['lib', 'components', 'ProductEmptyState', 'testDetectionLogic'])])

describe('SetupListeningIndicator', () => {
    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it('listens until the first data arrives, then links to the product', async () => {
        const statusLogic = productSetupStatusLogic({ productKey: ProductKey.TRACING })
        statusLogic.mount()
        statusLogic.actions.setDetectedStatus('needs-setup')

        render(
            <SetupListeningIndicator
                productKey={ProductKey.TRACING}
                statusLogic={detectionLogic}
                dataName="span"
                destination={{ label: 'Go to Tracing', url: '/tracing' }}
            />
        )
        expect(screen.getByText(/Listening for your first span/)).toBeInTheDocument()
        expect(screen.queryByText('Go to Tracing')).not.toBeInTheDocument()

        statusLogic.actions.setDetectedStatus('has-data')

        const link = await screen.findByText('Go to Tracing')
        expect(link.closest('a')).toHaveAttribute('href', expect.stringMatching(/\/tracing$/))
        expect(screen.queryByText(/Listening for your first span/)).not.toBeInTheDocument()
        statusLogic.unmount()
    })

    it('does not claim to be listening when detection cannot run', () => {
        const statusLogic = productSetupStatusLogic({ productKey: ProductKey.METRICS })
        statusLogic.mount()
        statusLogic.actions.setDetectedStatus('unknown')

        render(
            <SetupListeningIndicator
                productKey={ProductKey.METRICS}
                statusLogic={detectionLogic}
                dataName="metric"
                destination={{ label: 'Go to Metrics', url: '/metrics' }}
            />
        )
        expect(screen.queryByText(/Listening for your first metric/)).not.toBeInTheDocument()
        expect(screen.getByText(/can't check for incoming metrics/)).toBeInTheDocument()
        expect(screen.getByText('Go to Metrics')).toBeInTheDocument()
        statusLogic.unmount()
    })
})
