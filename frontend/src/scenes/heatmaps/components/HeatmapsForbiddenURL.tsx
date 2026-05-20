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
import { heatmapLogic } from 'scenes/heatmaps/scenes/heatmap/heatmapLogic'

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

export function HeatmapsForbiddenURL(): JSX.Element {
    const { dataUrl } = useValues(heatmapLogic({ id: 'new' }))
    const logic = authorizedUrlListLogic({
        ...defaultAuthorizedUrlProperties,
        type: AuthorizedUrlListType.TOOLBAR_URLS,
    })
    const { authorizedUrls } = useValues(logic)
    const { addUrl } = useActions(logic)

    const { urlToAuthorize, validationError } = useMemo(() => {
        if (!dataUrl) {
            return { urlToAuthorize: null, validationError: null }
        }
        const candidate = deriveAuthorizationCandidate(dataUrl)
        if (!candidate) {
            return { urlToAuthorize: null, validationError: 'Enter a valid URL to authorize' }
        }
        const error = validateProposedUrl(candidate, authorizedUrls, false, true)
        return { urlToAuthorize: candidate, validationError: error ?? null }
    }, [dataUrl, authorizedUrls])

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
                {dataUrl} is not an authorized URL.
                {validationError ? <> {validationError}.</> : null}
            </LemonBanner>
        </div>
    )
}
