import { render } from '@testing-library/react'

import { BodyDisplay } from 'scenes/session-recordings/apm/playerInspector/ItemPerformanceEvent'

describe('ItemPerformanceEvent', () => {
    it.each([
        ['[SessionReplay] Timeout while trying to read body', 'took too long'],
        ['[SessionReplay] Body too large to record (> 1000000 bytes)', 'too large'],
        ['[SessionReplay] Cannot read body of type Blob', "type isn't supported"],
        ['[SessionReplay] Failed to stringify response object', "couldn't be converted to text"],
        ['[SessionReplay] Failed to read body: AbortError', "couldn't read this body"],
        ['[SessionReplay] Some new message we do not map yet', "couldn't record this body"],
    ])('BodyDisplay explains the SDK diagnostic %s', (content, expectedExplanation) => {
        const { container } = render(<BodyDisplay content={content} headers={undefined} />)
        expect(container.textContent).toContain(expectedExplanation)
        // the raw SDK string stays visible for anyone who needs it
        expect(container.textContent).toContain(content)
    })
})
