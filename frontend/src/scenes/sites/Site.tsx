import './Site.scss'

import { useValues } from 'kea'

import {
    AuthorizedUrlListType,
    authorizedUrlListLogic,
    defaultAuthorizedUrlProperties,
} from 'lib/components/AuthorizedUrlList/authorizedUrlListLogic'
import { SceneExport } from 'scenes/sceneTypes'

import { SiteLogicProps, siteLogic } from './siteLogic'

export const scene: SceneExport<SiteLogicProps> = {
    component: Site,
    paramsToProps: ({ params: { url } }) => ({ url: decodeURIComponent(url) }),
    logic: siteLogic,
}

export function Site({ url }: SiteLogicProps): JSX.Element {
    const { launchUrl } = useValues(
        authorizedUrlListLogic({ ...defaultAuthorizedUrlProperties, type: AuthorizedUrlListType.TOOLBAR_URLS })
    )

    const decodedUrl = decodeURIComponent(url || '')

    return (
        <iframe
            className="Site"
            src={launchUrl(decodedUrl)}
            // allow-same-origin is particularly important here, because otherwise redirect_to_site cannot work
            // Note that combining allow-scripts and allow-same-origin effectively allows the iframe access to the
            // PostHog app, which is why it's important that users only add sites that they control here
            sandbox="allow-downloads allow-modals allow-forms allow-popups allow-scripts allow-same-origin"
        />
    )
}
