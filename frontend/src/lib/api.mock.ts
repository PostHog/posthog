import apiNoMock from 'lib/api'

type APIMockReturnType = {
    [K in keyof typeof apiNoMock]: jest.Mock<ReturnType<typeof apiNoMock[K]>, Parameters<typeof apiNoMock[K]>>
}

type APIRoute = {
    pathname: string
    search: string
    searchParams: Record<string, any>
    hash: string
    hashParams: Record<string, any>
    url: string
    data?: Record<string, any>
}

export const api = (apiNoMock as any) as APIMockReturnType

export const mockAPIGet = (cb: (url: APIRoute) => any): void => {
    beforeEach(async () => {
        api.get.mockImplementation(async (url, data?: Record<string, any>) => {
            // kea-router is mocked out, must `await import()` to get access to the utility
            return cb({ ...(await import('kea-router')).combineUrl(url), data })
        })
    })
}

export const mockAPICreate = (cb: (url: APIRoute) => any): void => {
    beforeEach(async () => {
        api.create.mockImplementation(async (url, data?: Record<string, any>) => {
            // kea-router is mocked out, must `await import()` to get access to the utility
            return cb({ ...(await import('kea-router')).combineUrl(url), data })
        })
    })
}