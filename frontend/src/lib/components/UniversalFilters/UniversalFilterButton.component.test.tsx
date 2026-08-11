import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { Provider } from 'kea'

import { cohortsModel } from '~/models/cohortsModel'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { initKeaTests } from '~/test/init'
import { ActionFilter, PropertyFilterType, PropertyOperator } from '~/types'

import { UniversalFilterButton } from './UniversalFilterButton'

describe('UniversalFilterButton', () => {
    beforeEach(() => {
        initKeaTests()
        cohortsModel.mount()
        propertyDefinitionsModel.mount()
    })

    afterEach(() => {
        cleanup()
    })

    const EVENT_WITH_PROPERTIES: ActionFilter = {
        id: '$pageview',
        name: '$pageview',
        type: 'events',
        order: 0,
        properties: [
            {
                key: '$current_url',
                value: ['/checkout'],
                operator: PropertyOperator.Exact,
                type: PropertyFilterType.Event,
            },
        ],
    }

    function renderButton(onClick?: () => void): void {
        render(
            <Provider>
                <UniversalFilterButton filter={EVENT_WITH_PROPERTIES} onClick={onClick} />
            </Provider>
        )
    }

    it('offers the property filter button when there is a handler to open the properties', () => {
        renderButton(() => {})
        expect(screen.getByRole('button')).toBeInTheDocument()
    })

    it('renders no button when read-only, so the property count is not a dead click target', () => {
        renderButton()
        expect(screen.queryByRole('button')).not.toBeInTheDocument()
    })
})
