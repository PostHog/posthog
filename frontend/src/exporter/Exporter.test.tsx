import { render } from '@testing-library/react'

import { Exporter } from '~/exporter/Exporter'
import { ExportType, ExportedData } from '~/exporter/types'

function makeDashboardExport(overrides: Partial<ExportedData> = {}): ExportedData {
    return {
        type: ExportType.Scene,
        dashboard: {
            id: 123,
            name: 'My shared dashboard',
            description: 'Description',
            tags: [],
            tiles: [],
        } as any,
        themes: [],
        allowAutoRefresh: true,
        ...overrides,
    }
}

describe('Exporter (shared dashboard)', () => {
    it('sets document title with PostHog suffix by default', () => {
        const initialTitle = document.title

        render(<Exporter {...makeDashboardExport()} />)

        expect(document.title).toBe('My shared dashboard • PostHog')

        // restore to avoid leaking between tests
        document.title = initialTitle
    })

    it('omits PostHog suffix from title when whitelabel is enabled', () => {
        const initialTitle = document.title

        render(<Exporter {...makeDashboardExport({ whitelabel: true })} />)

        expect(document.title).toBe('My shared dashboard')

        document.title = initialTitle
    })

    it('shows auto refresh text in header when allowAutoRefresh is true', () => {
        const { getByText } = render(<Exporter {...makeDashboardExport({ allowAutoRefresh: true })} />)

        expect(getByText('My shared dashboard')).toBeInTheDocument()
        expect(getByText(/Auto refresh every/i)).toBeInTheDocument()
    })

    it('does not show auto refresh text when allowAutoRefresh is false or missing', () => {
        const { queryByText, rerender } = render(<Exporter {...makeDashboardExport({ allowAutoRefresh: false })} />)

        expect(queryByText(/Auto refresh every/i)).toBeNull()

        rerender(<Exporter {...makeDashboardExport({ allowAutoRefresh: undefined })} />)
        expect(queryByText(/Auto refresh every/i)).toBeNull()
    })

    it('does not show auto refresh text for image exports even when allowAutoRefresh is true', () => {
        const { queryByText } = render(
            <Exporter {...makeDashboardExport({ type: ExportType.Image, allowAutoRefresh: true })} />
        )

        expect(queryByText(/Auto refresh every/i)).toBeNull()
    })
})
