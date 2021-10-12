import * as s from '../../src/utils/db/sql'

// mock functions that get data from postgres and give them the right types
type UnPromisify<F> = F extends (...args: infer A) => Promise<infer T> ? (...args: A) => T : never
export const getPluginRows = s.getPluginRows as unknown as jest.MockedFunction<UnPromisify<typeof s.getPluginRows>>
export const getPluginAttachmentRows = s.getPluginAttachmentRows as unknown as jest.MockedFunction<
    UnPromisify<typeof s.getPluginAttachmentRows>
>
export const getPluginConfigRows = s.getPluginConfigRows as unknown as jest.MockedFunction<
    UnPromisify<typeof s.getPluginConfigRows>
>
export const setPluginCapabilities = s.setPluginCapabilities as unknown as jest.MockedFunction<
    UnPromisify<typeof s.setPluginCapabilities>
>
export const setError = s.setError as unknown as jest.MockedFunction<UnPromisify<typeof s.setError>>
export const disablePlugin = s.disablePlugin as unknown as jest.MockedFunction<UnPromisify<void>>
