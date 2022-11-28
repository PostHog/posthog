import { PageHeader } from 'lib/components/PageHeader'
import { SceneExport } from 'scenes/sceneTypes'
import './ToolbarLaunch.scss'
import { Link } from 'lib/components/Link'
import { urls } from 'scenes/urls'
import { AuthorizedUrlList } from 'lib/components/AuthorizedUrlList/AuthorizedUrlList'
import { AuthorizedUrlListType } from 'lib/components/AuthorizedUrlList/authorizedUrlListLogic'
import { LemonDivider } from 'lib/components/LemonDivider'
import { LemonSwitch } from 'lib/components/LemonSwitch/LemonSwitch'
import { useActions, useValues } from 'kea'
import { userLogic } from 'scenes/userLogic'
import { ToolbarFeatures } from 'scenes/toolbar-launch/ToolbarFeatures'
import { ToolbarRedirectModal } from 'scenes/toolbar-launch/ToolbarRedirectModal'

export const scene: SceneExport = {
    component: ToolbarLaunch,
}

function ToolbarLaunch(): JSX.Element {
    const { user, userLoading } = useValues(userLogic)
    const { updateUser } = useActions(userLogic)

    return (
        <div className="toolbar-launch-page">
            <ToolbarRedirectModal />
            <PageHeader title="Toolbar" caption="The toolbar launches PostHog right in your app or website." />
            <LemonDivider />

            <div className="my-4">
                <LemonSwitch
                    data-attr="toolbar-authorized-toggle"
                    label="Enable the PostHog toolbar"
                    onChange={() =>
                        updateUser({
                            toolbar_mode: user?.toolbar_mode === 'disabled' ? 'toolbar' : 'disabled',
                        })
                    }
                    checked={user?.toolbar_mode !== 'disabled'}
                    disabled={userLoading}
                    bordered
                />
            </div>

            <h2 className="subtitle" id="urls">
                Authorized URLs for Toolbar
            </h2>
            <p>
                Click on the URL to launch the toolbar.{' '}
                {window.location.host === 'app.posthog.com' && 'Remember to disable your adblocker.'}
            </p>
            <AuthorizedUrlList type={AuthorizedUrlListType.TOOLBAR_URLS} addText={'Add authorized URL'} />

            <div className="footer-caption text-muted mt-4 text-center">
                Make sure you're using the <Link to={`${urls.projectSettings()}#snippet`}>HTML snippet</Link> or the
                latest <code>posthog-js</code> version.
            </div>

            <ToolbarFeatures />
        </div>
    )
}
