import apiNoMock from 'lib/api'
import { combineUrl } from 'kea-router'

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
        const methods = ['get', 'update', 'create', 'delete']
        for (const method of methods) {
            api[method as keyof typeof api].mockImplementation(async (url: string, data?: Record<string, any>) => {
                return cb({ ...combineUrl(url), data, method })
            })
        }
    })
}
