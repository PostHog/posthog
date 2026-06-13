import '@testing-library/jest-dom'

import { render } from '@testing-library/react'
import { Provider } from 'kea'

import { initKeaTests } from '~/test/init'
import { AnyPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

import { PropertyFilterButton } from './PropertyFilterButton'

describe('PropertyFilterButton', () => {
    beforeEach(() => {
        initKeaTests()
    })

    // The content span carries a native `title` only when the rich group card
    // tooltip is NOT used; a group-identity filter suppresses it and wraps the
    // chip in the formatted-card Tooltip instead.
    const contentTitle = (): string | null =>
        document.querySelector('.PropertyFilterButton-content')?.getAttribute('title') ?? null

    it.each([
        {
            description: 'a $group_key group filter (the group identity)',
            item: {
                key: '$group_key',
                type: PropertyFilterType.Group,
                group_type_index: 0,
                value: ['01953d33-82a2-0000-f577-8dcc2987f5ce'],
                operator: PropertyOperator.Exact,
            },
        },
        {
            description: 'an id group filter (a group property that often holds the key)',
            item: {
                key: 'id',
                type: PropertyFilterType.Group,
                group_type_index: 0,
                value: ['01953d33-82a2-0000-f577-8dcc2987f5ce'],
                operator: PropertyOperator.Exact,
            },
        },
    ])('suppresses the native title (uses the group card tooltip) for $description', ({ item }) => {
        render(
            <Provider>
                <PropertyFilterButton item={item as AnyPropertyFilter} onClick={jest.fn()} />
            </Provider>
        )

        expect(document.querySelector('.PropertyFilterButton-content')).toBeInTheDocument()
        // Native title is suppressed; the formatted-card Tooltip is used instead.
        // (The inverse — group *property* keys not triggering the card — is
        // covered by the isGroupCardFilterKey() unit tests.)
        expect(contentTitle()).toBeNull()
    })
})
