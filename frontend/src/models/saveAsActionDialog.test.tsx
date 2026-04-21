import '@testing-library/jest-dom'

import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { LocalFilter } from 'scenes/insights/filters/ActionFilter/entityFilterLogic'

import { useMocks } from '~/mocks/jest'
import { actionsModel } from '~/models/actionsModel'
import { initKeaTests } from '~/test/init'
import { EntityTypes, EventType, PropertyFilterType, PropertyOperator, RecordingEventType } from '~/types'

import {
    buildActionNameValidator,
    eventToActionStep,
    eventToSuggestedActionName,
    isAutocaptureWithElements,
    openSaveAsActionDialog,
    saveActionFromEvent,
    saveActionFromFilter,
} from './saveAsActionDialog'

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

type OpenFormConfig = Parameters<typeof LemonDialog.openForm>[0]

describe('saveAsActionDialog', () => {
    let openFormSpy: jest.SpyInstance<void, [OpenFormConfig]>
    let lastDialogConfig: OpenFormConfig | undefined
    let capturedBody: any
    let postStatus: number
    let postResponseBody: Record<string, unknown>

    beforeEach(() => {
        capturedBody = null
        postStatus = 200
        postResponseBody = { id: 42, name: 'Test', steps: [] }
        lastDialogConfig = undefined
        useMocks({
            get: { '/api/projects/:team/actions/': { results: [] } },
            post: {
                '/api/projects/:team/actions/': async (req) => {
                    capturedBody = await req.json()
                    if (postStatus >= 400) {
                        return [postStatus, postResponseBody]
                    }
                    return [postStatus, { ...postResponseBody, name: capturedBody.name, steps: capturedBody.steps }]
                },
            },
        })
        initKeaTests()
        actionsModel.mount()
        openFormSpy = jest.spyOn(LemonDialog, 'openForm').mockImplementation((config) => {
            lastDialogConfig = config
        })
    })

    afterEach(() => {
        openFormSpy.mockRestore()
    })

    async function submitCapturedDialog(actionName = lastDialogConfig?.initialValues?.actionName ?? ''): Promise<void> {
        if (!lastDialogConfig) {
            throw new Error('No dialog was opened')
        }
        await lastDialogConfig.onSubmit({ actionName })
    }

    describe('isAutocaptureWithElements', () => {
        it.each([
            ['autocapture with elements', makeAutocaptureEvent(), true],
            ['autocapture without elements', makeAutocaptureEvent({ elements: [] }), false],
            ['non-autocapture event', makeAutocaptureEvent({ event: '$pageview' }), false],
            [
                'recording event type with elements',
                { ...makeAutocaptureEvent(), fullyLoaded: true, playerTime: 0 } as RecordingEventType,
                true,
            ],
        ])('%s → %s', (_desc, event, expected) => {
            expect(isAutocaptureWithElements(event)).toBe(expected)
        })
    })

    describe('eventToActionStep', () => {
        it('includes url, url_matching and element-derived fields for a button event', () => {
            const step = eventToActionStep(makeAutocaptureEvent() as any, [])
            expect(step).toMatchObject({
                event: '$autocapture',
                url: 'https://example.com/page',
                url_matching: 'exact',
                text: 'Submit',
            })
        })

        it('applies the $event_type=submit property when present', () => {
            const step = eventToActionStep(
                makeAutocaptureEvent({
                    properties: { $current_url: 'https://example.com/page', $event_type: 'submit' },
                }) as any,
                []
            )
            expect(step.properties).toEqual([expect.objectContaining({ key: '$event_type', value: 'submit' })])
        })

        it('includes url/url_matching for $pageview', () => {
            const step = eventToActionStep(makeAutocaptureEvent({ event: '$pageview', elements: [] }) as any, [])
            expect(step).toMatchObject({ event: '$pageview', url: 'https://example.com/page', url_matching: 'exact' })
            expect(step.text).toBeUndefined()
            expect(step.selector).toBeUndefined()
        })

        it('omits url for custom events', () => {
            const step = eventToActionStep(
                makeAutocaptureEvent({ event: 'signed_up', elements: [], properties: {} }) as any,
                []
            )
            expect(step).toEqual({ event: 'signed_up' })
        })

        it('omits url/url_matching for $pageview when $current_url is missing', () => {
            const step = eventToActionStep(
                makeAutocaptureEvent({ event: '$pageview', elements: [], properties: {} }) as any,
                []
            )
            expect(step).toEqual({ event: '$pageview' })
        })
    })

    describe('eventToSuggestedActionName', () => {
        it.each([
            ['autocapture with text', makeAutocaptureEvent(), 'interacted with button with text "Submit"'],
            [
                '$pageview with url',
                makeAutocaptureEvent({
                    event: '$pageview',
                    properties: { $current_url: 'https://example.com/pricing' },
                }),
                'Pageview on /pricing',
            ],
            ['$pageview without url', makeAutocaptureEvent({ event: '$pageview', properties: {} }), 'Pageview action'],
            ['custom event', makeAutocaptureEvent({ event: 'signed_up', properties: {} }), 'signed_up event'],
        ])('%s → %s', (_desc, event, expected) => {
            expect(eventToSuggestedActionName(event as any)).toBe(expected)
        })
    })

    describe('buildActionNameValidator', () => {
        it.each([
            ['empty name', [], '', 'Action name is required'],
            ['whitespace-only name', [], '   ', 'Action name is required'],
            ['unique name', ['Other'], 'My action', undefined],
            ['colliding name', ['Existing action'], 'Existing action', 'An action with this name already exists'],
            [
                'collision ignoring surrounding whitespace in input',
                ['Existing action'],
                '  Existing action  ',
                'An action with this name already exists',
            ],
            [
                'collision ignoring surrounding whitespace in existing names',
                ['  Existing action  '],
                'Existing action',
                'An action with this name already exists',
            ],
            [
                'ignores empty/whitespace-only existing names',
                ['', '   ', 'Real action'],
                'Real action',
                'An action with this name already exists',
            ],
        ])('%s → %s', (_desc, existing, input, expected) => {
            const validator = buildActionNameValidator(() => existing)
            expect(validator(input)).toBe(expected)
        })

        it('reads existing names fresh on each call', () => {
            let names: string[] = []
            const validator = buildActionNameValidator(() => names)
            expect(validator('Foo')).toBeUndefined()
            names = ['Foo']
            expect(validator('Foo')).toBe('An action with this name already exists')
        })
    })

    describe('openSaveAsActionDialog', () => {
        it('opens the shared dialog with the suggested name', () => {
            openSaveAsActionDialog({ suggestedName: 'My suggestion', step: { event: '$autocapture' } })
            expect(lastDialogConfig?.initialValues?.actionName).toBe('My suggestion')
        })

        it('wires the uniqueness validator into the form', () => {
            actionsModel.actions.loadActionsSuccess([{ id: 1, name: 'Existing action', steps: [] }] as any)

            openSaveAsActionDialog({ suggestedName: 'Fresh', step: { event: '$autocapture' } })
            const validator = lastDialogConfig?.errors?.actionName as (value: string) => string | undefined
            expect(validator('')).toBe('Action name is required')
            expect(validator('Existing action')).toBe('An action with this name already exists')
            expect(validator('Fresh')).toBeUndefined()
        })

        it('posts the provided step unchanged on submit', async () => {
            const step = { event: '$autocapture', text: 'Submit', selector: '.btn' }

            openSaveAsActionDialog({ suggestedName: 'Named', step })
            await submitCapturedDialog('Named')

            expect(capturedBody.name).toBe('Named')
            expect(capturedBody.steps).toEqual([step])
            expect(capturedBody._create_in_folder).toBeUndefined()
        })

        it('passes _create_in_folder through when provided', async () => {
            openSaveAsActionDialog({
                suggestedName: 'Named',
                step: { event: '$autocapture' },
                createInFolder: 'Unfiled/Actions',
            })
            await submitCapturedDialog('Named')

            expect(capturedBody._create_in_folder).toBe('Unfiled/Actions')
        })
    })

    describe('saveActionFromFilter', () => {
        it('pre-fills name and step from a filter with $el_text', async () => {
            saveActionFromFilter(
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

            expect(lastDialogConfig?.initialValues?.actionName).toBe('Autocapture: "Submit"')
            await submitCapturedDialog()

            expect(capturedBody.steps[0]).toMatchObject({
                event: '$autocapture',
                text: 'Submit',
                text_matching: 'exact',
            })
            expect(capturedBody._create_in_folder).toBeUndefined()
        })

        it('posts the full filter → action step mapping for text + selector', async () => {
            saveActionFromFilter(
                makeFilter({
                    properties: [
                        {
                            key: '$el_text',
                            value: 'Submit',
                            operator: PropertyOperator.Exact,
                            type: PropertyFilterType.Event,
                        },
                        {
                            key: 'selector',
                            value: '.btn',
                            operator: PropertyOperator.Exact,
                            type: PropertyFilterType.Element,
                        },
                    ],
                })
            )
            await submitCapturedDialog()

            expect(capturedBody.name).toBe('Autocapture: "Submit"')
            expect(capturedBody.steps).toHaveLength(1)
            expect(capturedBody.steps[0]).toMatchObject({
                event: '$autocapture',
                text: 'Submit',
                text_matching: 'exact',
                selector: '.btn',
            })
        })
    })

    describe('saveActionFromEvent', () => {
        it('pre-fills name and step from an autocapture event and sets Unfiled/Actions folder', async () => {
            saveActionFromEvent(makeAutocaptureEvent(), [])

            expect(lastDialogConfig).not.toBeUndefined()
            await submitCapturedDialog('Clicked button "Submit"')

            expect(capturedBody.steps[0]).toMatchObject({
                event: '$autocapture',
                text: 'Submit',
                url: 'https://example.com/page',
                url_matching: 'exact',
            })
            expect(capturedBody._create_in_folder).toBe('Unfiled/Actions')
        })

        it('opens the dialog for $pageview events with a pathname-based suggested name', () => {
            saveActionFromEvent(
                makeAutocaptureEvent({
                    event: '$pageview',
                    elements: [],
                    properties: { $current_url: 'https://example.com/pricing' },
                }),
                []
            )
            expect(lastDialogConfig?.initialValues?.actionName).toBe('Pageview on /pricing')
        })

        it('opens the dialog for custom events with an event-name-based suggested name', () => {
            saveActionFromEvent(makeAutocaptureEvent({ event: 'signed_up', elements: [], properties: {} }), [])
            expect(lastDialogConfig?.initialValues?.actionName).toBe('signed_up event')
        })
    })

    describe('server error messages', () => {
        it.each([
            [
                'DRF field error on name',
                { name: ['This project already has an action with this name, ID 123'] },
                'This project already has an action with this name, ID 123',
            ],
            ['DRF non_field_errors', { non_field_errors: ['Oops'] }, 'Oops'],
            ['top-level detail', { detail: 'Generic detail message' }, 'Generic detail message'],
            ['empty body falls back to generic message', {}, 'Failed to create action. Please try again.'],
        ])('surfaces %s in the error toast', async (_desc, responseBody, expectedToast) => {
            const errorSpy = jest.spyOn(lemonToast, 'error')
            postStatus = 400
            postResponseBody = responseBody

            openSaveAsActionDialog({ suggestedName: 'Whatever', step: { event: '$autocapture' } })
            await submitCapturedDialog('Whatever')

            expect(errorSpy).toHaveBeenCalledWith(expectedToast)
            errorSpy.mockRestore()
        })
    })
})
