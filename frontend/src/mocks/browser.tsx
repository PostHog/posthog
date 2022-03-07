import { setupWorker } from 'msw'
import { handlers } from '~/mocks/handlers'

// Default handlers ensure no request is unhandled by msw
export const worker = setupWorker(...handlers)
