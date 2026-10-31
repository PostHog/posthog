import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { ModelPicker } from './ModelPicker'

describe('ModelPicker', () => {
    afterEach(cleanup)

    it('explains an open menu that has no models to offer', async () => {
        render(<ModelPicker model="" selectedProviderKeyId={null} onSelect={jest.fn()} groups={[]} />)

        await userEvent.click(screen.getByText('Select model'))

        expect(await screen.findByText('No models available.')).toBeInTheDocument()
    })

    it('selects a typed Azure deployment name that the provider did not list', async () => {
        const onSelect = jest.fn()
        render(
            <ModelPicker
                model=""
                selectedProviderKeyId={null}
                onSelect={onSelect}
                groups={[
                    {
                        provider: 'azure_openai',
                        providerKeyId: 'key-azure',
                        label: 'Azure OpenAI',
                        models: [],
                        allowsCustomModel: true,
                    },
                ]}
            />
        )

        await userEvent.click(screen.getByText('Select model'))
        await userEvent.type(
            await screen.findByPlaceholderText('Find a model or type a deployment name...'),
            ' my-gpt-4o '
        )
        await userEvent.click(screen.getByText('Azure OpenAI'))
        await userEvent.click(await screen.findByText('Use deployment "my-gpt-4o"'))

        expect(onSelect).toHaveBeenCalledWith('my-gpt-4o', 'key-azure')
    })
})
