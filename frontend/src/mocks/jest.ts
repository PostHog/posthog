import { setupServer } from 'msw/node'
import { handlers } from '~/mocks/handlers'

export const mswServer = setupServer(...handlers)

beforeAll(() => mswServer.listen())
afterEach(() => mswServer.resetHandlers())
afterAll(() => mswServer.close())
