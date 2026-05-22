import { cleanup, render } from '@testing-library/react'

import { SessionRecordingType } from '~/types'

import { PlaylistRecordingPreviewBlock, SectionContent } from './Playlist'

const TROUBLESHOOTING_HEADING = 'No matching recordings'

const mockEmptyState = (
    <div>
        <h3>{TROUBLESHOOTING_HEADING}</h3>
    </div>
)

const buildSection = (items: SessionRecordingType[]): PlaylistRecordingPreviewBlock => ({
    key: 'other',
    items,
    render: ({ item }) => <div data-attr={`recording-${item.id}`}>{item.id}</div>,
})

const aRecording: SessionRecordingType = {
    id: 'abc',
    viewed: false,
    viewers: [],
    recording_duration: 10,
    start_time: '2026-05-22T10:00:00.000Z',
    end_time: '2026-05-22T10:00:10.000Z',
    snapshot_source: 'web',
}

describe('SectionContent', () => {
    afterEach(() => {
        cleanup()
    })

    it('does not render the empty state troubleshooting heading while globalLoading is true', () => {
        const { queryByText, queryByTestId } = render(
            <SectionContent
                section={buildSection([])}
                loading={false}
                globalLoading={true}
                activeItemId={null}
                setActiveItemId={jest.fn()}
                emptyState={mockEmptyState}
            />
        )

        expect(queryByText(TROUBLESHOOTING_HEADING)).toBeNull()
        // The loading skeleton state is rendered instead
        expect(queryByTestId('recording-abc')).toBeNull()
    })

    it('does not render the empty state while the per-section loading flag is true', () => {
        const { queryByText } = render(
            <SectionContent
                section={buildSection([])}
                loading={true}
                globalLoading={false}
                activeItemId={null}
                setActiveItemId={jest.fn()}
                emptyState={mockEmptyState}
            />
        )

        expect(queryByText(TROUBLESHOOTING_HEADING)).toBeNull()
    })

    it('renders the empty state only when no loading flag is active and items are empty', () => {
        const { getByText } = render(
            <SectionContent
                section={buildSection([])}
                loading={false}
                globalLoading={false}
                activeItemId={null}
                setActiveItemId={jest.fn()}
                emptyState={mockEmptyState}
            />
        )

        expect(getByText(TROUBLESHOOTING_HEADING)).toBeTruthy()
    })

    it('renders items when present even while globalLoading is true', () => {
        const { getByTestId, queryByText } = render(
            <SectionContent
                section={buildSection([aRecording])}
                loading={false}
                globalLoading={true}
                activeItemId={null}
                setActiveItemId={jest.fn()}
                emptyState={mockEmptyState}
            />
        )

        expect(getByTestId('recording-abc')).toBeTruthy()
        expect(queryByText(TROUBLESHOOTING_HEADING)).toBeNull()
    })
})
