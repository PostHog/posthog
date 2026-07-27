import './Site.scss'

import { useValues } from 'kea'

import {
    AuthorizedUrlListType,
    authorizedUrlListLogic,
    defaultAuthorizedUrlProperties,
} from 'lib/components/AuthorizedUrlList/authorizedUrlListLogic'
import { NotFound } from 'lib/components/NotFound'
import { SpinnerOverlay } from 'lib/lemon-ui/Spinner'
import { SceneExport } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'

import { SiteLogicProps, siteLogic } from './siteLogic'

export const scene: SceneExport<SiteLogicProps> = {
    component: Site,
    paramsToProps: ({ params: { url } }) => ({ url: decodeURIComponent(url) }),
    logic: siteLogic,
}

export function Site({ url }: SiteLogicProps): JSX.Element {
    const { launchUrl, checkUrlIsSafeToFrame } = useValues(
        authorizedUrlListLogic({ ...defaultAuthorizedUrlProperties, type: AuthorizedUrlListType.TOOLBAR_URLS })
    )
    const { currentTeamLoading } = useValues(teamLogic)

    const decodedUrl = decodeURIComponent(url || '')

    // Authorized URLs are populated from the team, so until it loads we can't tell whether the URL
    // is allowed — show a spinner rather than briefly flashing the NotFound error to a valid link.
    if (currentTeamLoading) {
        return <SpinnerOverlay sceneLevel />
    }

    // The iframe runs with `allow-scripts allow-same-origin`, so anything loaded into it can reach
    // the PostHog app. Only render URLs the team has authorized, and never non-http(s) schemes.
    if (!checkUrlIsSafeToFrame(decodedUrl)) {
        return (
            <NotFound
                object="site preview"
                caption="This URL can't be previewed. Site previews are only available for domains added to your project's authorized URLs."
            />
        )
    }

    return (
        <iframe
            className="Site"
            title="Site preview"
            src={launchUrl(decodedUrl)}
            // allow-same-origin is particularly important here, because otherwise redirect_to_site cannot work
            // Note that combining allow-scripts and allow-same-origin effectively allows the iframe access to the
            // PostHog app, which is why it's important that users only add sites that they control here
            sandbox="allow-downloads allow-modals allow-forms allow-popups allow-scripts allow-same-origin"
        />
    )
}
