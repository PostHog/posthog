import { status } from '../src/utils/status'

// NOTE: in testing we use the pino-pretty transport, which results in a handle
// that we need to close to allow Jest to exit properly.
afterAll(() => status.close())
