import { LemonButton, LemonInput, LemonLabel, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { PluginInstallationType } from '~/types'

export function AdvancedInstallModal(): JSX.Element {
    const { preflight } = useValues(preflightLogic)

    const { advancedInstallModalOpen, pluginError, loading, sourcePluginName, customPluginUrl, localPluginUrl } =
        useValues(pluginsLogic)
    const { closeAdvancedInstallModal, installPlugin, setSourcePluginName, setCustomPluginUrl, setLocalPluginUrl } =
        useActions(pluginsLogic)

    return (
        <LemonModal
            onClose={closeAdvancedInstallModal}
            isOpen={advancedInstallModalOpen}
            width={600}
            title="Advanced app installation"
            footer={
                <>
                    <LemonButton type="secondary" onClick={closeAdvancedInstallModal}>
                        Cancel
                    </LemonButton>
                </>
            }
        >
            <div className="space-y-4">
                <LemonBanner type="warning">
                    <>
                        <b>Advanced features ahead</b>
                        <br />
                        Create and install your <b>own apps</b> or apps from <b>third-parties</b>.
                    </>
                </LemonBanner>

                {pluginError ? <LemonBanner type="error">{pluginError}</LemonBanner> : null}

                <div className="">
                    <LemonLabel>Code your own app</LemonLabel>
                    <p>
                        Write your app directly in PostHog.{' '}
                        <Link to="https://posthog.com/docs/apps" target="_blank">
                            Read the documentation for more information!
                        </Link>
                    </p>
                    <div className="flex items-center gap-2">
                        <LemonInput
                            value={sourcePluginName}
                            disabled={loading}
                            onChange={setSourcePluginName}
                            placeholder={`For example: "Hourly Weather Sync App"`}
                            className="flex-1"
                        />
                        <LemonButton
                            disabledReason={!sourcePluginName ? 'Please enter a name' : undefined}
                            loading={loading}
                            type="primary"
                            onClick={() => installPlugin(sourcePluginName, PluginInstallationType.Source)}
                        >
                            Start coding
                        </LemonButton>
                    </div>
                </div>

                <div className="">
                    <LemonLabel>Install from GitHub, GitLab or npm</LemonLabel>
                    <p>
                        To install a third-party or custom app, paste its URL below. For{' '}
                        <Link
                            to="https://docs.github.com/en/github/authenticating-to-github/creating-a-personal-access-token"
                            target="_blank"
                        >
                            GitHub
                        </Link>
                        {', '}
                        <Link to="https://docs.gitlab.com/ee/user/profile/personal_access_tokens.html" target="_blank">
                            GitLab
                        </Link>
                        {' and '}
                        <Link to="https://docs.npmjs.com/creating-and-viewing-access-tokens" target="_blank">
                            npm
                        </Link>{' '}
                        private repositories, append <code>?private_token=TOKEN</code> to the end of the URL.
                        <br />
                        <b className="text-warning">Warning: Only install apps from trusted sources.</b>
                    </p>
                    <div className="flex items-center gap-2">
                        <LemonInput
                            value={customPluginUrl}
                            disabled={loading}
                            onChange={setCustomPluginUrl}
                            placeholder="https://github.com/user/repo"
                            className="flex-1"
                        />
                        <LemonButton
                            disabledReason={!customPluginUrl ? 'Please enter a url' : undefined}
                            loading={loading}
                            type="primary"
                            onClick={() => installPlugin(customPluginUrl, PluginInstallationType.Custom)}
                        >
                            Fetch and install
                        </LemonButton>
                    </div>
                </div>
                {preflight && !preflight.cloud && (
                    <>
                        <div className="">
                            <LemonLabel>Install Local App</LemonLabel>
                            <p>To install a local app from this computer/server, give its full path below.</p>
                            <div className="flex items-center gap-2">
                                <LemonInput
                                    value={localPluginUrl}
                                    disabled={loading}
                                    onChange={setLocalPluginUrl}
                                    placeholder="/var/posthog/plugins/helloworldplugin"
                                    className="flex-1"
                                />
                                <LemonButton
                                    disabledReason={!localPluginUrl ? 'Please enter a path' : undefined}
                                    loading={loading}
                                    type="primary"
                                    onClick={() => installPlugin(localPluginUrl, PluginInstallationType.Local)}
                                >
                                    Install
                                </LemonButton>
                            </div>
                        </div>
                    </>
                )}
            </div>
        </LemonModal>
    )
}
