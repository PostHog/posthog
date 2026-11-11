import '@testing-library/jest-dom'

import { fireEvent, render } from '@testing-library/react'

import { initKeaTests } from '~/test/init'
import { AccessControlLevel } from '~/types'

import { saveToDatasetButtonLogic } from '../../../datasets/saveToDatasetButtonLogic'
import { makeRawNode } from '../testFixtures'
import { RawLoad } from '../types'
import { DatasetButtonSlot } from './DatasetButtonSlot'

const source = { traceId: 'trace-1', timestamp: '2026-09-01T10:15:00Z', sourceId: 'span-1' }
const ready: RawLoad = { status: 'ready', raw: makeRawNode({ id: 'span-1' }) }

function setAiObservabilityAccess(level: AccessControlLevel): void {
    const appContext = window.POSTHOG_APP_CONTEXT!
    appContext.resource_access_control = { ...appContext.resource_access_control, llm_analytics: level }
}

describe('DatasetButtonSlot', () => {
    let savedAccess: NonNullable<typeof window.POSTHOG_APP_CONTEXT>['resource_access_control']

    beforeEach(() => {
        initKeaTests()
        savedAccess = window.POSTHOG_APP_CONTEXT!.resource_access_control
        setAiObservabilityAccess(AccessControlLevel.Editor)
    })

    afterEach(() => {
        window.POSTHOG_APP_CONTEXT!.resource_access_control = savedAccess
    })

    it.each<[string, RawLoad | undefined, typeof source | null, 'placeholder' | 'busy' | 'retry' | 'real' | 'nothing']>(
        [
            ['not requested yet', undefined, null, 'placeholder'],
            ['loading', { status: 'loading' }, null, 'busy'],
            ['failed', { status: 'error', failure: 'failed' }, null, 'retry'],
            ['ready with a source', ready, source, 'real'],
            [
                'ready without a source',
                { status: 'ready', raw: makeRawNode({ id: 's', withEvent: false }) },
                null,
                'nothing',
            ],
            ['not found', { status: 'error', failure: 'not_found' }, null, 'nothing'],
        ]
    )('%s', (_name, raw, itemSource, expected) => {
        const onLoad = jest.fn()
        const { container } = render(<DatasetButtonSlot raw={raw} source={itemSource} onLoad={onLoad} />)
        const placeholder = container.querySelector('[data-attr="save-to-dataset-placeholder"]')
        const real = container.querySelector('[data-attr="save-to-dataset-open"]')

        expect(!!placeholder).toBe(['placeholder', 'busy', 'retry'].includes(expected))
        expect(!!real).toBe(expected === 'real')
        if (placeholder) {
            expect(placeholder.getAttribute('aria-disabled')).toBe('false')
            expect(placeholder.getAttribute('aria-busy')).toBe(String(expected === 'busy'))
            expect(placeholder.getAttribute('aria-label')).toBe(
                expected === 'retry' ? "Add to dataset. Couldn't load this step's event. Click to try again." : null
            )
            fireEvent.click(placeholder)
            expect(onLoad).toHaveBeenCalled()
        }
        if (real) {
            fireEvent.mouseEnter(real)
            fireEvent.click(real)
            expect(onLoad).not.toHaveBeenCalled()
        }
        if (expected === 'nothing') {
            expect(container).toBeEmptyDOMElement()
        }
    })

    it.each<[string, AccessControlLevel, (placeholder: Element) => void, boolean]>([
        [
            'opens for a click before the read finishes',
            AccessControlLevel.Editor,
            (button) => fireEvent.click(button),
            true,
        ],
        [
            'opens for a press that the swap interrupts before its click',
            AccessControlLevel.Editor,
            (button) => fireEvent.mouseDown(button),
            true,
        ],
        [
            'stays closed after a click and then a press elsewhere',
            AccessControlLevel.Editor,
            (button) => {
                fireEvent.click(button)
                fireEvent.pointerDown(document.body)
            },
            false,
        ],
        [
            'stays closed for a press by a viewer',
            AccessControlLevel.Viewer,
            (button) => fireEvent.mouseDown(button),
            false,
        ],
    ])('after the swap the dropdown %s', (_name, level, interact, opens) => {
        setAiObservabilityAccess(level)
        const { container, rerender } = render(
            <DatasetButtonSlot raw={{ status: 'loading' }} source={null} onLoad={jest.fn()} />
        )
        interact(container.querySelector('[data-attr="save-to-dataset-placeholder"]')!)

        rerender(<DatasetButtonSlot raw={ready} source={source} onLoad={jest.fn()} />)

        expect(saveToDatasetButtonLogic.findMounted()?.values.dropdownVisible).toBe(opens)
    })

    it('disables the placeholder like the real button for a viewer', () => {
        setAiObservabilityAccess(AccessControlLevel.Viewer)

        const { container } = render(<DatasetButtonSlot raw={undefined} source={null} onLoad={jest.fn()} />)

        expect(
            container.querySelector('[data-attr="save-to-dataset-placeholder"]')?.getAttribute('aria-disabled')
        ).toBe('true')
    })
})
