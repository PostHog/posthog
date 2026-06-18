import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import api from 'lib/api'

import { tagsModel } from '~/models/tagsModel'
import { initKeaTests } from '~/test/init'
import { CyclotronJobInputSchemaType } from '~/types'

import CyclotronJobInputTicketTags from './CyclotronJobInputTicketTags'

// `schema` is part of the renderer contract but unused by this component.
const schema = { key: 'tags', type: 'posthog_ticket_tags' } as CyclotronJobInputSchemaType

describe('CyclotronJobInputTicketTags', () => {
    beforeEach(() => {
        jest.spyOn(api.tags, 'list').mockResolvedValue(['existing_tag'])
        initKeaTests()
        tagsModel.mount()
    })

    afterEach(() => {
        cleanup()
        jest.restoreAllMocks()
    })

    // Regression: the workflow tags input must be an always-on multi-select, not ObjectTags'
    // click-to-edit toggle. The toggle collapses (unmounting the input) the moment focus leaves,
    // which made removing/adding a tag impossible inside the ReactFlow node panel.
    it('renders an always-editable input without a click-to-edit toggle', async () => {
        render(<CyclotronJobInputTicketTags schema={schema} value={['plan_enterprise']} onChange={jest.fn()} />)

        await waitFor(() => expect(screen.getByText('plan_enterprise')).toBeInTheDocument())
        // The text input is present immediately — no "Edit tags"/"Add tag" gate to click first.
        expect(document.querySelector('input[type="text"]')).toBeInTheDocument()
        expect(screen.queryByText('Edit tags')).not.toBeInTheDocument()
        expect(screen.queryByText('Add tag')).not.toBeInTheDocument()
    })

    it('removes a tag via its × and reports the trimmed list through onChange', async () => {
        const onChange = jest.fn()
        render(
            <CyclotronJobInputTicketTags
                schema={schema}
                value={['plan_enterprise', 'unknown_slack_default_enterprise']}
                onChange={onChange}
            />
        )

        await waitFor(() => expect(screen.getByText('plan_enterprise')).toBeInTheDocument())

        const closeButtons = document.querySelectorAll<HTMLButtonElement>('.LemonSnack__close button')
        expect(closeButtons).toHaveLength(2)

        await userEvent.click(closeButtons[0])

        expect(onChange).toHaveBeenCalledWith(['unknown_slack_default_enterprise'])
    })

    it('handles an undefined value as an empty tag list', async () => {
        render(<CyclotronJobInputTicketTags schema={schema} value={undefined} onChange={jest.fn()} />)

        await waitFor(() => expect(document.querySelector('input[type="text"]')).toBeInTheDocument())
        expect(document.querySelectorAll('.LemonSnack__close button')).toHaveLength(0)
    })
})
