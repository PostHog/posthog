import { setupServer } from 'msw/node'
import { handlers } from '~/mocks/handlers'
import { Mocks, mocksToHandlers } from '~/mocks/utils'
import { useFeatures } from '~/mocks/features'

export const mswServer = setupServer(...handlers)
export const useMocks = (mocks: Mocks): void => mswServer.use(...mocksToHandlers(mocks))

beforeAll(() => {
    useFeatures([])
    mswServer.listen()
})
afterEach(() => mswServer.resetHandlers())
afterAll(() => mswServer.close())
