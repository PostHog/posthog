import { HrefAnchor } from './href-anchors'

export const WORKFLOW_RUN_PARAM = 'ph_workflow_run'

// `clicktracking="off"` is the ESP de-facto standard; `data-ph-no-track` is our name. An unquoted `clicktracking=off/>`
// reads its slash into the value, and both it and a space after `off` were opt-outs before the HTML parser read them.
const CLICK_TRACKING_OFF = /^off\s*\/?$/i

export const hasClickTrackingOptOutAttribute = (anchor: Pick<HrefAnchor, 'attribute'>): boolean =>
    anchor.attribute('data-ph-no-track') !== undefined ||
    CLICK_TRACKING_OFF.test(anchor.attribute('clicktracking')?.value ?? '')

export const isNeverClickTracked = (anchor: Pick<HrefAnchor, 'attribute'>): boolean =>
    hasClickTrackingOptOutAttribute(anchor) || anchor.attribute('ses:no-track') !== undefined

const paramName = (param: string): string => {
    const name = param.split('=')[0]
    try {
        return decodeURIComponent(name)
    } catch {
        return name
    }
}

const isWorkflowRunParam = (param: string): boolean => paramName(param) === WORKFLOW_RUN_PARAM

export const removeWorkflowRunTag = (url: string): string => {
    const hashIndex = url.indexOf('#')
    const beforeHash = hashIndex === -1 ? url : url.slice(0, hashIndex)
    const hash = hashIndex === -1 ? '' : url.slice(hashIndex)
    const queryIndex = beforeHash.indexOf('?')
    if (queryIndex === -1) {
        return url
    }
    const params = beforeHash.slice(queryIndex + 1).split('&')
    const kept = params.filter((param) => !isWorkflowRunParam(param))
    if (kept.length === params.length) {
        return url
    }
    const query = kept.join('&')
    return `${beforeHash.slice(0, queryIndex)}${query ? `?${query}` : ''}${hash}`
}
