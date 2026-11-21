import { UseMaxToolOptions, useMaxTool } from './useMaxTool'

/** Registers a page's PostHog AI tool and renders nothing. Shell code loads it lazily, because it may not import this layer. */
export function MaxToolRegistration({ maxToolProps }: { maxToolProps: Omit<UseMaxToolOptions, 'active'> }): null {
    useMaxTool({ ...maxToolProps, active: true })
    return null
}
