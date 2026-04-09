import '@testing-library/jest-dom'

import { act, cleanup, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { LocalFilter } from 'scenes/insights/filters/ActionFilter/entityFilterLogic'

import { useMocks } from '~/mocks/jest'
import { actionsModel } from '~/models/actionsModel'
import { initKeaTests } from '~/test/init'
import { EntityTypes, EventType, PropertyFilterType, PropertyOperator } from '~/types'

import { saveAsActionLogic } from './saveAsActionLogic'

function makeAutocaptureEvent(overrides: Partial<EventType> = {}): EventType {
    return {
        id: 'test-id',
        distinct_id: 'user-1',
        event: '$autocapture',
        timestamp: '2026-01-01T00:00:00Z',
        properties: { $current_url: 'https://example.com/page' },
        elements: [{ tag_name: 'button', text: 'Submit', attributes: {}, order: 0 }],
        ...overrides,
    } as EventType
}

function makeFilter(overrides: Partial<LocalFilter> = {}): LocalFilter {
    return {
        id: '$autocapture',
        name: '$autocapture',
        type: EntityTypes.EVENTS,
        order: 0,
        uuid: 'test-uuid',
        properties: [],
        ...overrides,
    }
}

async function submitDialog(): Promise<void> {
    const submitButton = screen.getByRole('button', { name: 'Submit' })
    await userEvent.click(submitButton)
}

describe('saveAsActionLogic', () => {
    let capturedBody: any
    let postStatus: number

    afterEach(async () => {
        cleanup()
        await act(async () => {
            await new Promise((r) => setTimeout(r, 0))
        })
        document.querySelectorAll('body > div:not(#root)').forEach((el) => el.remove())
        saveAsActionLogic.unmount()
    })

    beforeEach(() => {
        capturedBody = null
        postStatus = 200
        useMocks({
            get: { '/api/projects/:team/actions/': { results: [] } },
            post: {
                '/api/projects/:team/actions/': async (req) => {
                    capturedBody = await req.json()
                    if (postStatus >= 400) {
                        return [postStatus, { detail: 'fail' }]
                    }
                    return [postStatus, { id: 42, name: capturedBody.name, steps: capturedBody.steps }]
                },
            },
        })
        initKeaTests()
        actionsModel.mount()
        saveAsActionLogic.mount()
    })

    describe('openSaveAsActionDialog', () => {
        it('opens the shared dialog with the suggested name', async () => {
            saveAsActionLogic.actions.openSaveAsActionDialog({
                suggestedName: 'My suggestion',
                step: { event: '$autocapture' },
            })

            await waitFor(() => {
                expect(screen.getByDisplayValue('My suggestion')).toBeInTheDocument()
            })
        })

        it('disables the submit button until a name is entered', async () => {
            saveAsActionLogic.actions.openSaveAsActionDialog({
                suggestedName: '',
                step: { event: '$autocapture' },
            })

            await waitFor(() => expect(screen.getByTestId('save-as-action-name')).toBeInTheDocument())

            const submitButton = screen.getByRole('button', { name: 'Submit' })
            expect(submitButton).toHaveAttribute('aria-disabled', 'true')
        })

        it('posts the provided step unchanged on submit', async () => {
            const step = {
                event: '$autocapture',
                text: 'Submit',
                selector: '.btn',
            }

            saveAsActionLogic.actions.openSaveAsActionDialog({ suggestedName: 'Named', step })

            await waitFor(() => expect(screen.getByDisplayValue('Named')).toBeInTheDocument())
            await submitDialog()

            await waitFor(() => expect(capturedBody).not.toBeNull())
            expect(capturedBody.name).toBe('Named')
            expect(capturedBody.steps).toEqual([step])
            expect(capturedBody._create_in_folder).toBeUndefined()
        })

        it('passes _create_in_folder through when provided', async () => {
            saveAsActionLogic.actions.openSaveAsActionDialog({
                suggestedName: 'Named',
                step: { event: '$autocapture' },
                createInFolder: 'Unfiled/Actions',
            })

            await waitFor(() => expect(screen.getByDisplayValue('Named')).toBeInTheDocument())
            await submitDialog()

            await waitFor(() => expect(capturedBody).not.toBeNull())
            expect(capturedBody._create_in_folder).toBe('Unfiled/Actions')
        })

        it('creates the action via API on successful submit', async () => {
            saveAsActionLogic.actions.openSaveAsActionDialog({
                suggestedName: 'Named',
                step: { event: '$autocapture' },
            })

            await waitFor(() => expect(screen.getByDisplayValue('Named')).toBeInTheDocument())
            await submitDialog()

            await waitFor(() => expect(capturedBody).not.toBeNull())
            expect(capturedBody.name).toBe('Named')
        })

        it('still posts to the API when the server would return an error', async () => {
            postStatus = 500

            saveAsActionLogic.actions.openSaveAsActionDialog({
                suggestedName: 'ErrorCase',
                step: { event: '$autocapture' },
            })

            await waitFor(() => expect(screen.getByDisplayValue('ErrorCase')).toBeInTheDocument())
            await submitDialog()

            await waitFor(() => expect(capturedBody).not.toBeNull())
            expect(capturedBody.name).toBe('ErrorCase')
        })
    })

    describe('saveFromFilter', () => {
        it('pre-fills name and step from a filter with $el_text', async () => {
            saveAsActionLogic.actions.saveFromFilter(
                makeFilter({
                    properties: [
                        {
                            key: '$el_text',
                            value: 'Submit',
                            operator: PropertyOperator.Exact,
                            type: PropertyFilterType.Event,
                        },
                    ],
                })
            )

            await waitFor(() => expect(screen.getByDisplayValue('Autocapture: "Submit"')).toBeInTheDocument())
            await submitDialog()

            await waitFor(() => expect(capturedBody).not.toBeNull())
            expect(capturedBody.steps[0]).toMatchObject({
                event: '$autocapture',
                text: 'Submit',
                text_matching: 'exact',
            })
            expect(capturedBody._create_in_folder).toBeUndefined()
        })
    })

    describe('saveFromEvent', () => {
        it('pre-fills name and step from an autocapture event and sets Unfiled/Actions folder', async () => {
            saveAsActionLogic.actions.saveFromEvent(makeAutocaptureEvent(), [])

            await waitFor(() => expect(screen.getByTestId('save-as-action-name')).toBeInTheDocument())
            await submitDialog()

            await waitFor(() => expect(capturedBody).not.toBeNull())
            expect(capturedBody.steps[0]).toMatchObject({
                event: '$autocapture',
                text: 'Submit',
                url: 'https://example.com/page',
                url_matching: 'exact',
            })
            expect(capturedBody._create_in_folder).toBe('Unfiled/Actions')
        })

        it('is a no-op for non-autocapture events', () => {
            saveAsActionLogic.actions.saveFromEvent(makeAutocaptureEvent({ event: '$pageview' }), [])

            expect(screen.queryByTestId('save-as-action-name')).not.toBeInTheDocument()
        })
    })
})
