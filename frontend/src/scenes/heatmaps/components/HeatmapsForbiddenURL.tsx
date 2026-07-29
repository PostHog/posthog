import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { IconPlus } from '@posthog/icons'
import { LemonBanner } from '@posthog/lemon-ui'

import {
    AuthorizedUrlListType,
    authorizedUrlListLogic,
    defaultAuthorizedUrlProperties,
    sanitizePossibleWildCardedURL,
    validateProposedUrl,
} from 'lib/components/AuthorizedUrlList/authorizedUrlListLogic'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { heatmapsBrowserLogic } from 'scenes/heatmaps/components/heatmapsBrowserLogic'

const HOST_WILDCARD_REGEX = /^https?:\/\/[^/]*\*/

function deriveAuthorizationCandidate(dataUrl: string): string | null {
    if (HOST_WILDCARD_REGEX.test(dataUrl)) {
        const match = dataUrl.match(/^(https?:\/\/[^/]+)/)
        return match ? match[1] : null
    }
    try {
        return sanitizePossibleWildCardedURL(dataUrl).origin
    } catch {
        return null
    }
}

/** `url` defaults to the heatmap data URL; pass it when another URL is the unauthorized one. */
export function HeatmapsForbiddenURL({ url }: { url?: string | null }): JSX.Element {
    const { dataUrl } = useValues(heatmapsBrowserLogic)
    const forbiddenUrl = url ?? dataUrl
    const logic = authorizedUrlListLogic({
        ...defaultAuthorizedUrlProperties,
        type: AuthorizedUrlListType.TOOLBAR_URLS,
    })
    const { authorizedUrls } = useValues(logic)
    const { addUrl } = useActions(logic)

    const { urlToAuthorize, validationError } = useMemo(() => {
        if (!forbiddenUrl) {
            return { urlToAuthorize: null, validationError: null }
        }
        const candidate = deriveAuthorizationCandidate(forbiddenUrl)
        if (!candidate) {
            return { urlToAuthorize: null, validationError: 'Enter a valid URL to authorize' }
        }
        const error = validateProposedUrl(candidate, authorizedUrls, false, true)
        return { urlToAuthorize: candidate, validationError: error ?? null }
    }, [forbiddenUrl, authorizedUrls])

    return (
        <div className="my-2">
            <LemonBanner
                type="error"
                action={
                    urlToAuthorize && !validationError
                        ? {
                              children: 'Authorize URL',
                              icon: <IconPlus />,
                              onClick: () => {
                                  addUrl(urlToAuthorize)
                                  lemonToast.success(`Authorized ${urlToAuthorize}`)
                              },
                              'data-attr': 'heatmaps-authorize-url',
                          }
                        : undefined
                }
            >
                {forbiddenUrl} is not an authorized URL.
                {validationError ? <> {validationError}.</> : null}
            </LemonBanner>
        </div>
    )
}
