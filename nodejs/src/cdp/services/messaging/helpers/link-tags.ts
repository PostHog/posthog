export const WORKFLOW_RUN_PARAM = 'ph_workflow_run'

// `clicktracking="off"` is the ESP de-facto standard; `data-ph-no-track` is our name.
const CLICK_TRACKING_OPT_OUT_REGEX = /\bclicktracking\s*=\s*["']?off["']?|\bdata-ph-no-track\b/i
const SES_NO_TRACK_ATTR_REGEX = /\bses:no-track\b/i

export const hasClickTrackingOptOut = (openingTag: string): boolean => CLICK_TRACKING_OPT_OUT_REGEX.test(openingTag)

export const hasSesNoTrack = (openingTag: string): boolean => SES_NO_TRACK_ATTR_REGEX.test(openingTag)

export const isNeverClickTracked = (openingTag: string): boolean =>
    hasClickTrackingOptOut(openingTag) || hasSesNoTrack(openingTag)

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
