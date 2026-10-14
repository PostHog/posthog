import { render } from '@testing-library/react'

import { LemonRadio } from './LemonRadio'

describe('LemonRadio', () => {
    it('renders the group-level data-attr', () => {
        // Hyphenated JSX attributes skip TypeScript's excess property check, so a
        // silently dropped data-attr prop never fails typecheck.
        const { container } = render(
            <LemonRadio
                data-attr="my-radio-group"
                value="a"
                onChange={() => {}}
                options={[
                    { value: 'a', label: 'A' },
                    { value: 'b', label: 'B' },
                ]}
            />
        )
        expect(container.querySelector('[data-attr="my-radio-group"]')).not.toBeNull()
    })
})
