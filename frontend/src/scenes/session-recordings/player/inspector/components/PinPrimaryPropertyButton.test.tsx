import '@testing-library/jest-dom'

import { cleanup, render } from '@testing-library/react'
import { Provider } from 'kea'

import { getPrimaryPropertyForEvent } from 'lib/utils/events'

import { primaryEventPropertiesModel } from '~/models/primaryEventPropertiesModel'
import { initKeaTests } from '~/test/init'

import { PinPrimaryPropertyButton } from './PinPrimaryPropertyButton'

const INTERACTIVE = '[data-attr="replay-pin-primary-property"]'
const BUILT_IN = '[data-attr="replay-pin-primary-property-builtin"]'

describe('PinPrimaryPropertyButton', () => {
    let logic: ReturnType<typeof primaryEventPropertiesModel.build>

    beforeEach(() => {
        initKeaTests()
        logic = primaryEventPropertiesModel()
        logic.mount()
    })

    afterEach(() => {
        cleanup()
    })

    const renderButton = (eventName: string, propertyKey: string, isRowHovered: boolean): HTMLElement =>
        render(
            <Provider>
                <PinPrimaryPropertyButton eventName={eventName} propertyKey={propertyKey} isRowHovered={isRowHovered} />
            </Provider>
        ).container

    it('shows a disabled built-in pin for the taxonomy primary property', () => {
        const taxonomyKey = getPrimaryPropertyForEvent('$pageview')
        expect(taxonomyKey).toBeTruthy()

        const container = renderButton('$pageview', taxonomyKey!, false)

        const builtIn = container.querySelector(BUILT_IN)
        expect(builtIn).toBeInTheDocument()
        expect(builtIn).toHaveAttribute('aria-disabled', 'true')
        expect(container.querySelector(INTERACTIVE)).not.toBeInTheDocument()
    })

    it('renders nothing for non-primary rows of a taxonomy-locked event', () => {
        const taxonomyKey = getPrimaryPropertyForEvent('$pageview')
        const container = renderButton('$pageview', `${taxonomyKey}_something_else`, true)

        expect(container.querySelector(BUILT_IN)).not.toBeInTheDocument()
        expect(container.querySelector(INTERACTIVE)).not.toBeInTheDocument()
    })

    const revealCases: { name: string; pinned: boolean; hovered: boolean; hidden: boolean }[] = [
        { name: 'hidden when not pinned and the row is not hovered', pinned: false, hovered: false, hidden: true },
        { name: 'revealed when the row is hovered', pinned: false, hovered: true, hidden: false },
        { name: 'always shown when pinned, even without hover', pinned: true, hovered: false, hidden: false },
    ]

    it.each(revealCases)('$name', ({ pinned, hovered, hidden }) => {
        if (pinned) {
            logic.actions.loadPrimaryPropertiesSuccess({ my_event: 'my_prop' }, { names: ['my_event'] })
        }

        const container = renderButton('my_event', 'my_prop', hovered)

        const button = container.querySelector(INTERACTIVE)
        expect(button).toBeInTheDocument()
        expect(container.querySelector(BUILT_IN)).not.toBeInTheDocument()
        expect(button?.classList.contains('opacity-0')).toBe(hidden)
    })
})
