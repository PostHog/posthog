import { status } from '../src/utils/status'

// NOTE: in testing we use the pino-pretty transport, which results in a handle
// that we need to close to allow Jest to exit properly.
// TODO: update jest modules path to not include the plugin-server/src/ i.e.
// nothing in the functional tests should be importing anything from the
// plugin-server code.
afterAll(() => status.close())
