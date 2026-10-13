import '@testing-library/jest-dom'

import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { initKeaTests } from '~/test/init'
import { experimentsTabLogic } from '~/toolbar/experiments/experimentsTabLogic'
import { WebExperimentVariant } from '~/toolbar/experiments/WebExperimentVariant'
import { toolbarConfigLogic } from '~/toolbar/toolbarConfigLogic'

describe('WebExperimentVariant', () => {
    const setVariantTransforms = (selectors: string[]): void => {
        experimentsTabLogic.actions.setExperimentFormValue('variants', {
            test: { transforms: selectors.map((selector) => ({ selector })), rollout_percentage: 100 },
        })
    }

    beforeEach(() => {
        // The toolbar calls `global.fetch` directly, and mounting the tab logic loads the experiment list
        global.fetch = jest.fn(() =>
            Promise.resolve({ ok: true, json: () => Promise.resolve({ results: [] }) } as any as Response)
        )
        initKeaTests()
        toolbarConfigLogic.build({ apiURL: 'http://localhost', accessToken: 'test-token' }).mount()
        experimentsTabLogic().mount()
    })

    it('opens the only transformation on mount', () => {
        setVariantTransforms(['.headline'])

        render(<WebExperimentVariant variant="test" />)

        expect(screen.getByText('Select element')).toBeInTheDocument()
    })

    it('lets you open a later transformation once the variant has several', async () => {
        setVariantTransforms(['.headline', '.subtitle'])

        render(<WebExperimentVariant variant="test" />)
        await userEvent.click(screen.getByText('.subtitle'))

        const secondPanel = screen.getByText('.subtitle').closest('.LemonCollapsePanel') as HTMLElement
        expect(secondPanel).toHaveAttribute('aria-expanded', 'true')
        expect(within(secondPanel).getByText('Select element')).toBeInTheDocument()
    })
})
