import { render, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'

describe('ObjectTags', () => {
    it('removes a tag via the x without collapsing edit mode', async () => {
        const onChange = jest.fn()
        const { container } = render(
            <ObjectTags tags={['alpha', 'beta']} onChange={onChange} saving={false} tagsAvailable={['alpha', 'beta']} />
        )

        await userEvent.click(within(container).getByText('Edit tags'))

        const closeButtons = container.querySelectorAll('.LemonSnack__close button')
        expect(closeButtons).toHaveLength(2)

        await userEvent.click(closeButtons[0] as HTMLElement)

        // The click must actually remove the tag (not just close editing before it lands)
        expect(onChange).toHaveBeenCalledWith(['beta'])
        expect(container.querySelector('input[type="text"]')).not.toBeNull()
    })
})
