import { useActions, useValues } from 'kea'

import { LemonSkeleton, LemonSwitch, Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { businessKnowledgeSettingsLogic } from './businessKnowledgeSettingsLogic'

export function LearnFromSupportSetting(): JSX.Element {
    const { settings, settingsLoading, settingsSaving } = useValues(businessKnowledgeSettingsLogic)
    const { setLearnFromSupportEnabled, loadSettings } = useActions(businessKnowledgeSettingsLogic)

    if (settingsLoading && !settings) {
        return <LemonSkeleton className="h-10 w-80" />
    }
    if (!settings) {
        return (
            <p className="m-0">
                Couldn't load this setting. <Link onClick={() => loadSettings()}>Try again</Link>
            </p>
        )
    }

    const supportOff = !settings.support_enabled
    const cannotEnable = supportOff && !settings.learn_from_support_enabled

    return (
        <div className="flex flex-col gap-2">
            <LemonSwitch
                bordered
                checked={settings.learn_from_support_enabled}
                onChange={setLearnFromSupportEnabled}
                loading={settingsSaving}
                disabledReason={cannotEnable ? 'Turn on Support to learn from resolved tickets' : undefined}
                label="Learn from support"
                // data-attr is a frozen autocapture / Playwright key. Do not rename.
                data-attr="business-knowledge-learn-from-support"
            />
            {supportOff ? (
                <Link to={urls.settings('environment-conversations')}>
                    Turn on Support to learn from resolved tickets
                </Link>
            ) : null}
        </div>
    )
}
