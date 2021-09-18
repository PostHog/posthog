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
    method: string
}

export const api = (apiNoMock as any) as APIMockReturnType

export const mockAPI = (cb: (url: APIRoute) => any): void => {
    beforeEach(async () => {
        api.get.mockImplementation(async (url, data?: Record<string, any>) => {
            return cb({ ...(await import('kea-router')).combineUrl(url), data, method: 'get' })
        }),
            api.update.mockImplementation(async (url, data?: Record<string, any>) => {
                return cb({ ...(await import('kea-router')).combineUrl(url), data, method: 'update' })
            })
        api.create.mockImplementation(async (url, data?: Record<string, any>) => {
            return cb({ ...(await import('kea-router')).combineUrl(url), data, method: 'create' })
        })
        api.delete.mockImplementation(async (url, data?: Record<string, any>) => {
            return cb({ ...(await import('kea-router')).combineUrl(url), data, method: 'delete' })
        })
    })
}
