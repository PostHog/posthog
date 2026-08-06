import { actionToUrl as actionToUrlReal } from 'kea-router'

import { trackedActionToUrl } from './trackedActionToUrl'
import { trackUrlChange } from './urlChangeTracker'

jest.mock('kea-router', () => {
    const actual = jest.requireActual('kea-router')
    return {
        ...actual,
        actionToUrl: jest.fn(() => jest.fn()),
    }
})

jest.mock('./urlChangeTracker', () => ({
    trackUrlChange: jest.fn(),
}))

const actionToUrl = actionToUrlReal as unknown as jest.Mock
const trackUrlChangeMock = trackUrlChange as unknown as jest.Mock

const setupWrapped = (input: Record<string, any>): Record<string, (payload: any) => any> => {
    actionToUrl.mockClear()
    const fakeLogic = { pathString: 'test.logic', props: {} } as any
    trackedActionToUrl(input)(fakeLogic)
    expect(actionToUrl).toHaveBeenCalledTimes(1)
    return actionToUrl.mock.calls[0][0]
}

describe('trackedActionToUrl', () => {
    beforeEach(() => {
        trackUrlChangeMock.mockClear()
    })

    it.each([
        ['string', '/insights'],
        ['array', ['/sql', undefined, { q: 'SELECT 1' }, { replace: true }]],
    ] as const)('passes through the %s response and reports it to the tracker', (_, returnValue) => {
        const handler = jest.fn().mockReturnValue(returnValue)
        const wrapped = setupWrapped({ syncUrl: handler })

        const response = wrapped.syncUrl({})

        expect(handler).toHaveBeenCalledWith({})
        expect(response).toEqual(returnValue)
        expect(trackUrlChangeMock).toHaveBeenCalledWith(returnValue, 'test.logic', 'syncUrl')
    })
})
