import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { ModelPicker } from './ModelPicker'

describe('ModelPicker', () => {
    it('explains an open menu that has no models to offer', async () => {
        render(
            <ModelPicker
                model=""
                selectedProviderKeyId={null}
                onSelect={jest.fn()}
                groups={[]}
                data-attr="test-model-selector"
            />
        )

        await userEvent.click(screen.getByText('Select model'))

        expect(await screen.findByText('No models available.')).toBeTruthy()
    })
})
