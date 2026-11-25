import { useActions, useValues } from 'kea'

import { LemonSkeleton, LemonSwitch, Link } from '@posthog/lemon-ui'
import { Button, Field, FieldLabel, Skeleton, Switch } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { businessKnowledgeSettingsLogic } from './businessKnowledgeSettingsLogic'
import { LearnFromPastTicketsSetting } from './LearnFromPastTicketsSetting'
import { QuillRetryText } from './QuillRetryText'

export function LearnFromSupportSetting(): JSX.Element {
    const { settings, settingsLoading, settingsSaving } = useValues(businessKnowledgeSettingsLogic)
    const { setLearnFromSupportEnabled, loadSettings } = useActions(businessKnowledgeSettingsLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (settingsLoading && !settings) {
        return todayRailNav ? <Skeleton className="h-10 w-80" /> : <LemonSkeleton className="h-10 w-80" />
    }
    if (!settings) {
        if (todayRailNav) {
            return <QuillRetryText message="Couldn't load this setting." onRetry={() => loadSettings()} />
        }
        return (
            <p className="m-0">
                Couldn't load this setting. <Link onClick={() => loadSettings()}>Try again</Link>
            </p>
        )
    }

    const supportOff = !settings.support_enabled
    const cannotEnable = supportOff && !settings.learn_from_support_enabled

    if (todayRailNav) {
        return (
            <div className="flex flex-col gap-4">
                <div className="flex flex-col items-start gap-2">
                    <Field orientation="horizontal" className="w-fit">
                        <Switch
                            id="business-knowledge-learn-from-support"
                            checked={settings.learn_from_support_enabled}
                            onCheckedChange={setLearnFromSupportEnabled}
                            disabled={settingsSaving}
                            disabledReason={cannotEnable ? 'Turn on Support to learn from resolved tickets' : undefined}
                            // data-attr is a frozen autocapture / Playwright key. Do not rename.
                            data-attr="business-knowledge-learn-from-support"
                        />
                        <FieldLabel htmlFor="business-knowledge-learn-from-support">Learn from support</FieldLabel>
                    </Field>
                    {supportOff ? (
                        <Button
                            variant="link"
                            size="inline"
                            nativeButton={false}
                            render={<LinkPrimitive to={urls.settings('environment-conversations')} />}
                        >
                            Turn on Support to learn from resolved tickets
                        </Button>
                    ) : null}
                </div>
                <LearnFromPastTicketsSetting />
            </div>
        )
    }

    return (
        <div className="flex flex-col gap-4">
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
            <LearnFromPastTicketsSetting />
        </div>
    )
}
