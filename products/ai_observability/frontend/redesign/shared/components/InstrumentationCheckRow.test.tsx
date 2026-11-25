import { cleanup, render } from '@testing-library/react'

import {
    AIObservabilityInstrumentationCheckEnumApi,
    InstrumentationCheckStatusEnumApi,
} from '../../../generated/api.schemas'
import { InstrumentationCheckRow } from './InstrumentationCheckRow'

const { Ok, Warning, Pending, Dismissed } = InstrumentationCheckStatusEnumApi

describe('InstrumentationCheckRow', () => {
    afterEach(cleanup)

    it.each([
        [Ok, null, false],
        [Warning, 'Not applicable', true],
        [Pending, null, false],
        [Dismissed, 'Recheck', false],
    ])('a %s check offers the button %p and a docs link: %s', (status, buttonText, linksDocs) => {
        const { container } = render(
            <InstrumentationCheckRow
                check={{
                    key: AIObservabilityInstrumentationCheckEnumApi.Sessions,
                    status,
                    title: 'Sessions',
                    detail: 'No traces include $ai_session_id.',
                    docs_url: 'https://posthog.com/docs/ai-observability/sessions',
                    stats: {},
                }}
                pendingCheckKey={null}
                busy={false}
                onDismiss={jest.fn()}
                onRestore={jest.fn()}
            />
        )

        expect(container.querySelector('button')?.textContent ?? null).toBe(buttonText)
        expect(container.querySelector('a[href="https://posthog.com/docs/ai-observability/sessions"]') !== null).toBe(
            linksDocs
        )
    })
})
