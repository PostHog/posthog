import { fireEvent, render } from '@testing-library/react'
import { BindLogic, Provider } from 'kea'

import { initKeaTests } from '~/test/init'

import { errorPropertiesLogic } from '../errorPropertiesLogic'
import { ErrorTrackingStackFrame } from '../types'
import { CollapsibleFrame } from './CollapsibleFrame'

const baseFrame: ErrorTrackingStackFrame = {
    raw_id: 'raw-frame-id',
    mangled_name: 'a',
    line: 1,
    column: 2,
    source: 'main.jsbundle',
    in_app: true,
    resolved_name: null,
    lang: 'javascript',
    resolved: false,
    resolve_failure: null,
    module: null,
}

describe('CollapsibleFrame', () => {
    beforeEach(() => {
        initKeaTests()
    })

    test.each([
        ['unresolved', { resolved: false }, 'could not resolve this frame'],
        ['resolved without source', { resolved: true }, 'its symbol set has no source code'],
    ])('a %s frame explains on click why it has no source code', (_, overrides, expectedText) => {
        const { container } = render(
            <Provider>
                <BindLogic logic={errorPropertiesLogic} props={{ id: 'exception-uuid', properties: {} }}>
                    <CollapsibleFrame
                        frame={{ ...baseFrame, ...overrides }}
                        recordLoading={false}
                        expanded={false}
                        onExpandedChange={() => {}}
                    />
                </BindLogic>
            </Provider>
        )
        const trigger = container.querySelector('button.collapsible-frame-header') as HTMLButtonElement

        expect(trigger.disabled).toBe(false)
        fireEvent.click(trigger)
        expect(container.querySelector('[data-attr="frame-unavailable-reason"]')?.textContent).toContain(expectedText)
    })
})
