import '@testing-library/jest-dom'

import { render, screen, cleanup } from '@testing-library/react'

import { initKeaTests } from '~/test/init'

import { SessionReplayWidgetPreview } from './SessionReplayWidgetPreview'

jest.mock('scenes/session-recordings/playlist/SessionRecordingPreview', () => ({
    SessionRecordingPreview: ({ recording }: { recording: { id: string } }): JSX.Element => (
        <div data-attr="session-recording-preview">{recording.id}</div>
    ),
}))

describe('SessionReplayWidgetPreview', () => {
    afterEach(() => {
        cleanup()
    })

    beforeEach(() => {
        initKeaTests()
    })

    it('renders recording rows using SessionRecordingPreview', () => {
        render(<SessionReplayWidgetPreview />)

        expect(screen.getAllByTestId('session-recording-preview')).toHaveLength(3)
        expect(screen.getByText('overview-recording-1')).toBeInTheDocument()
        expect(screen.getByText('overview-recording-2')).toBeInTheDocument()
        expect(screen.getByText('overview-recording-3')).toBeInTheDocument()
    })
})
