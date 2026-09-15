import { fireEvent, render, waitFor } from '@testing-library/react'

import { Exporter } from '~/exporter/Exporter'
import { ExportType, ExportedData } from '~/exporter/types'
import { initKeaTests } from '~/test/init'

beforeEach(() => {
    initKeaTests()
})

afterEach(() => {
    jest.restoreAllMocks()
})

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

    it('shows auto refresh text in header', () => {
        const { getAllByText } = render(<Exporter {...makeDashboardExport()} />)

        // The dashboard header can be rendered multiple times depending on internal
        // export layout/portal behavior.
        const headings = getAllByText('My shared dashboard')
        expect(headings.length).toBeGreaterThan(0)
        expect(getAllByText(/Auto refresh every/i).length).toBeGreaterThan(0)
    })

    it('renders the share once the password is accepted, without reloading', async () => {
        const unlocked = makeDashboardExport()
        const realFetch = global.fetch
        // Only the share URL is answered here - everything else stays on the suite's usual mocks
        jest.spyOn(global, 'fetch').mockImplementation(async (url, options: RequestInit = {}) => {
            if (url !== window.location.href) {
                return realFetch(url, options)
            }
            if (options.method === 'POST') {
                return { status: 200, json: async () => ({ shareToken: 'jwt-token' }) } as any
            }
            return { ok: true, json: async () => unlocked } as any
        })

        const { getByPlaceholderText, getByText, getAllByText } = render(<Exporter type={ExportType.Unlock} />)
        fireEvent.change(getByPlaceholderText('••••••••••'), { target: { value: 'correct' } })
        fireEvent.click(getByText('Unlock'))

        await waitFor(() => expect(getAllByText('My shared dashboard').length).toBeGreaterThan(0))
    })

    it('applies the share theme to the unlock screen', () => {
        render(<Exporter type={ExportType.Unlock} theme="dark" />)

        expect(document.body.getAttribute('theme')).toBe('dark')

        document.body.removeAttribute('theme')
    })

    it('does not show auto refresh text for image exports', () => {
        const { container } = render(<Exporter {...makeDashboardExport({ type: ExportType.Image })} />)

        // Image exports use a minimal header (h1 + description), not the Scene header with "Auto refresh every"
        expect(container.querySelector('.SharedDashboard-header')).toBeNull()
    })
})
