import { cleanup, render } from '@testing-library/react'

import type { TracePreviewMissingReasonApi } from '../../../generated/api.schemas'
import type { TraceCellStatus } from '../types'
import { TracePreviewCell } from './TracePreviewCell'

const PREVIEW = 'Why was I charged twice this month?'

describe('TracePreviewCell', () => {
    afterEach(cleanup)

    it.each<[string, string | null, TracePreviewMissingReasonApi | null, TraceCellStatus, string, string | null]>([
        ['a skeleton while loading', null, null, 'loading', 'Loading…', null],
        ['the preview with its full text on hover', PREVIEW, null, 'ready', PREVIEW, PREVIEW],
        ['a dash for no preview', null, null, 'ready', '-', null],
        ['a placeholder for a preview too large to read', null, 'too_large', 'ready', 'Too large to preview', null],
        ['a placeholder for a preview that timed out', null, 'timed_out', 'ready', 'Preview timed out', null],
        ['a failure mark when it could not load', null, null, 'error', '', null],
    ])('renders %s', (_name, text, missingReason, status, shown, title) => {
        const { container } = render(<TracePreviewCell text={text} missingReason={missingReason} status={status} />)

        expect(container.textContent).toBe(shown)
        expect(container.querySelector('[title]')?.getAttribute('title') ?? null).toBe(title)
        expect(container.querySelector('.ph-no-capture')?.textContent ?? null).toBe(title)
        expect(!!container.querySelector('[role="img"][aria-label^="Couldn\'t load"]')).toBe(status === 'error')
    })
})
