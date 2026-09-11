import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BindLogic } from 'kea'

import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { PlayerShareMenu } from 'scenes/session-recordings/player/share/PlayerShareMenu'

import { initKeaTests } from '~/test/init'

jest.mock('lib/utils/copyToClipboard', () => ({ copyToClipboard: jest.fn() }))

describe('PlayerShareMenu', () => {
    const logicProps = { sessionRecordingId: 'abc123', playerKey: 'test' }

    beforeEach(() => {
        initKeaTests()
        sessionRecordingPlayerLogic(logicProps).mount()
    })

    it('copies the recording link', async () => {
        render(
            <BindLogic logic={sessionRecordingPlayerLogic} props={logicProps}>
                <PlayerShareMenu />
            </BindLogic>
        )
        await userEvent.click(screen.getByText('Share'))
        await userEvent.click(screen.getByText('Copy link'))
        expect(copyToClipboard).toHaveBeenCalledWith(expect.stringContaining('abc123'), 'recording link')
    })
})
