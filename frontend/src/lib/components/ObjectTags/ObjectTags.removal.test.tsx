import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'

describe('ObjectTags', () => {
    it('shows the placeholder when the only stored tag is blank', () => {
        render(<ObjectTags tags={['']} staticOnly />)

        expect(screen.getByText('—')).toBeTruthy()
    })

    it('removes a tag via the x without collapsing edit mode', async () => {
        const onChange = jest.fn()
        render(
            <ObjectTags tags={['alpha', 'beta']} onChange={onChange} saving={false} tagsAvailable={['alpha', 'beta']} />
        )

        await userEvent.click(screen.getByText('Edit tags'))

        const closeButtons = document.querySelectorAll('.LemonSnack__close button')
        expect(closeButtons).toHaveLength(2)

        await userEvent.click(closeButtons[0] as HTMLElement)

        // The click must actually remove the tag (not just close editing before it lands)
        expect(onChange).toHaveBeenCalledWith(['beta'])
        expect(document.querySelector('input[type="text"]')).not.toBeNull()
    })
})
